#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReleaseGuard CLI Runner for HER Hack-Astron #8 (Spark-X2.6-4B × SkillHub Challenge).

Modes:
  --check-env         Inspect GPU/CPU/RAM, free disk space, HF/GGUF cache, and exact model sizes/SHAs.
  --dry-run           Verify the full SkillHub ChangeRadar + 7-Gate Verifier + HTML Walkthrough pipeline
                      end-to-end without model weights (explicitly watermarked DRY_RUN_SYNTHETIC_PREVIEW).
  --download-and-run  Run real local `Spark-X2.6-4B` inference across the 5 OSS release samples
                      (via OpenAI-compatible local server `llama.cpp`/`Ollama`/`vLLM` OR HF `transformers`),
                      checking hardware & asking confirmation before downloading any missing weights.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from releaseguard.html_report import generate_html_walkthrough  # noqa: E402
from releaseguard.parser import load_all_samples  # noqa: E402
from releaseguard.prompts import build_spark_messages  # noqa: E402
from releaseguard.skill_bridge import (  # noqa: E402
    run_changeradar_pipeline,
    verify_skillhub_package,
)
from releaseguard.spark_runner import (  # noqa: E402
    SPARK_GGUF_Q4_BYTES,
    SPARK_GGUF_Q4_FILENAME,
    SPARK_GGUF_Q8_BYTES,
    SPARK_GGUF_Q8_FILENAME,
    SPARK_GGUF_REPO,
    SPARK_GGUF_REVISION,
    SPARK_HF_REPO,
    SPARK_HF_REVISION,
    SPARK_HF_TOTAL_BYTES,
    DryRunPreviewRunner,
    EnvironmentReport,
    OpenAICompatSparkRunner,
    TransformersSparkRunner,
    confirm_weight_download,
    inspect_environment,
)
from releaseguard.template_filler import fill_hf_discussion_template  # noqa: E402
from releaseguard.verifier import verify_spark_output  # noqa: E402


def print_env_report(env: EnvironmentReport) -> None:
    print("=" * 78)
    print("  ReleaseGuard Hardware, Cache & Spark-X2.6-4B Weight Sizing Report")
    print("=" * 78)
    print(f"  OS / Python        : {env.os_platform} | Python {env.python_version}")
    print(f"  CPU                : {env.cpu_model} ({env.logical_cores} logical processors)")
    print(f"  System RAM         : {env.ram_total_gib:.2f} GiB")
    print(f"  NVIDIA GPU         : {env.nvidia_gpu or 'Not detected (CPU / Integrated Graphics)'}")
    print(f"  Disk ({env.disk_drive})          : {env.disk_free_gib:.2f} GiB free / {env.disk_total_gib:.2f} GiB total")
    print(f"  HF Hub Cache       : {env.hf_cache_dir}")
    print(f"  Cached Spark Repos : {env.cached_spark_repos or 'None'}")
    print(f"  Local GGUF Weights : {env.local_gguf_files or 'None'}")
    print(f"  Active Spark APIs  : {env.active_local_servers or 'None probing 18080/30000/11434/1234'}")
    print("-" * 78)
    print("  Official Spark-X2.6-4B Checkpoints & Exact Download Sizes:")
    bf16 = env.models_catalog["transformers_bf16"]
    q4 = env.models_catalog["gguf_q4_k_m"]
    q8 = env.models_catalog["gguf_q8_0"]
    print(
        f"  1) {bf16['repo_id']} (rev {bf16['revision_sha'][:12]})\n"
        f"     Size: {bf16['total_bytes']:,} bytes ({bf16['size_gib']:.3f} GiB / {bf16['size_gb_decimal']:.3f} GB) — {bf16['format']}"
    )
    print(
        f"  2) {q4['repo_id']} :: {q4['filename']} (rev {q4['revision_sha'][:12]})\n"
        f"     Size: {q4['total_bytes']:,} bytes ({q4['size_gib']:.3f} GiB / {q4['size_gb_decimal']:.3f} GB) — {q4['format']}"
    )
    print(
        f"  3) {q8['repo_id']} :: {q8['filename']} (rev {q8['revision_sha'][:12]})\n"
        f"     Size: {q8['total_bytes']:,} bytes ({q8['size_gib']:.3f} GiB / {q8['size_gb_decimal']:.3f} GB) — {q8['format']}"
    )
    print("-" * 78)
    print(f"  Recommendation     : {env.recommended_runtime}")
    print("=" * 78)


def download_gguf_if_requested(env: EnvironmentReport, quant: str, auto_yes: bool) -> Path:
    filename = SPARK_GGUF_Q4_FILENAME if quant == "Q4_K_M" else SPARK_GGUF_Q8_FILENAME
    expected_bytes = SPARK_GGUF_Q4_BYTES if quant == "Q4_K_M" else SPARK_GGUF_Q8_BYTES
    dest = WORKSPACE_ROOT / "models" / filename
    if dest.exists() and dest.stat().st_size == expected_bytes:
        print(f"Reusing matching cached GGUF weight: {dest} ({expected_bytes:,} bytes)")
        return dest

    if not confirm_weight_download(env, f"{SPARK_GGUF_REPO}/{filename}", SPARK_GGUF_REVISION, expected_bytes, auto_yes):
        raise SystemExit("Aborted weight download per user confirmation rule.")

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{SPARK_GGUF_REPO}/resolve/{SPARK_GGUF_REVISION}/{filename}"
    print(f"Downloading {url} -> {dest} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "ReleaseGuard/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out_f:
        downloaded = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out_f.write(chunk)
            downloaded += len(chunk)
            pct = (downloaded / expected_bytes) * 100.0
            print(f"\r  Downloaded {downloaded / (1024**3):.2f} / {expected_bytes / (1024**3):.2f} GiB ({pct:.1f}%)", end="")
    print("\nGGUF weight download complete.")
    return dest


def execute_pipeline(args: argparse.Namespace, env: EnvironmentReport, is_dry_run: bool) -> int:
    skill_dir = WORKSPACE_ROOT / ".agents" / "skills" / "changeradar"
    samples_root = WORKSPACE_ROOT / "data" / "samples"
    outputs_dir = WORKSPACE_ROOT / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    skill_prov = verify_skillhub_package(skill_dir, run_self_checks=True)
    print(
        f"[SkillHub Verified] {skill_prov.namespace}/{skill_prov.slug}@{skill_prov.version} "
        f"({skill_prov.fingerprint[:26]}..., {skill_prov.files_verified} files SHA-256 matched, 6/6 self-checks OK)"
    )

    all_samples = load_all_samples(samples_root)
    if args.sample:
        all_samples = [s for s in all_samples if s.sample_id.startswith(args.sample)]
        if not all_samples:
            print(f"No sample matching {args.sample!r}", file=sys.stderr)
            return 2

    if is_dry_run:
        runner: Any = DryRunPreviewRunner()
        run_tag = "dry_run_preview"
    else:
        run_tag = f"real_spark_{args.thinking}"
        if args.download_gguf:
            gguf_path = download_gguf_if_requested(env, args.gguf_quant, args.yes)
            print(
                f"\nGGUF ready at: {gguf_path}\n"
                f"Ensure your local server is running, e.g.:\n"
                f'  llama-server -m "{gguf_path}" --port 18080 -c 16384 --jinja\n'
            )

        if args.backend == "openai-compat":
            api_base = args.api_base
            if not api_base and env.active_local_servers:
                api_base = env.active_local_servers[0]["api_base"]
            api_base = api_base or "http://127.0.0.1:18080/v1"
            runner = OpenAICompatSparkRunner(
                api_base=api_base,
                model_name=args.served_model_name,
                model_revision=args.model_revision or SPARK_GGUF_REVISION,
                quantization=args.gguf_quant,
                thinking_mode=args.thinking,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
        else:
            model_target = args.model_id
            is_cached = Path(model_target).exists() or any(
                "spark-x2.6-4b" in c.lower() for c in env.cached_spark_repos
            )
            if not is_cached:
                if not confirm_weight_download(
                    env, SPARK_HF_REPO, SPARK_HF_REVISION, SPARK_HF_TOTAL_BYTES, args.yes
                ):
                    return 1
            runner = TransformersSparkRunner(
                model_id_or_path=model_target,
                revision=args.model_revision or SPARK_HF_REVISION,
                thinking_mode=args.thinking,
                temperature=args.temperature,
                max_new_tokens=args.max_tokens,
                local_files_only=False,
            )

    sample_records: list[dict[str, Any]] = []
    passed_samples = 0
    verified_items_total = 0
    items_total = 0

    for sample in all_samples:
        trace_out = outputs_dir / "runs" / run_tag / sample.sample_id / "trace.json"
        if not is_dry_run and getattr(args, "resume", False) and trace_out.exists():
            cached_rec = json.loads(trace_out.read_text(encoding="utf-8"))
            if not cached_rec.get("inference", {}).get("is_dry_run", True):
                # Re-verify raw_text deterministically so verification report stays in sync with verifier.py
                cr = run_changeradar_pipeline(skill_dir, sample.repo_dir, sample.patch_diff_raw)
                raw_txt = cached_rec["inference"]["raw_text"]
                items, step0, thinking_trace, report = verify_spark_output(raw_txt, sample, cr)
                cached_rec["changeradar"] = cr.to_dict()
                cached_rec["step0_contract"] = step0
                cached_rec["thinking_trace"] = thinking_trace
                cached_rec["checklist_items"] = [it.to_dict() for it in items]
                cached_rec["verification"] = report.to_dict()
                trace_out.write_text(json.dumps(cached_rec, indent=2, ensure_ascii=False), encoding="utf-8")

                sample_records.append(cached_rec)
                if report.all_gates_passed:
                    passed_samples += 1
                verified_items_total += report.verified_items_count
                items_total += report.total_items_count
                print(
                    f"  [{sample.sample_id}] REUSED CACHED REAL RUN | "
                    f"gates={'PASS (7/7)' if report.all_gates_passed else 'PARTIAL'} "
                    f"| items={report.verified_items_count}/{report.total_items_count} "
                    f"| latency={cached_rec['inference']['latency_ms']} ms",
                    flush=True,
                )
                continue

        print(f"  [{sample.sample_id}] Running ChangeRadar AST + Spark-X2.6-4B inference...", flush=True)
        cr = run_changeradar_pipeline(skill_dir, sample.repo_dir, sample.patch_diff_raw)
        messages = build_spark_messages(sample, skill_prov, cr)
        inf = runner.generate(messages, sample, cr)
        items, step0, thinking_trace, report = verify_spark_output(inf.raw_text, sample, cr)

        if report.all_gates_passed:
            passed_samples += 1
        verified_items_total += report.verified_items_count
        items_total += report.total_items_count

        rec = {
            "sample_id": sample.sample_id,
            "project": sample.project,
            "from_version": sample.from_version,
            "to_version": sample.to_version,
            "release_url": sample.release_url,
            "license": sample.license,
            "release_lines": [
                {"line_id": ln.line_id, "line_num": ln.line_num, "text": ln.text}
                for ln in sample.release_lines
            ],
            "patch_diff_raw": sample.patch_diff_raw,
            "ground_truth": sample.ground_truth,
            "changeradar": cr.to_dict(),
            "prompt_messages": messages,
            "inference": inf.to_dict(),
            "step0_contract": step0,
            "thinking_trace": thinking_trace,
            "checklist_items": [it.to_dict() for it in items],
            "verification": report.to_dict(),
        }
        sample_records.append(rec)

        trace_out = outputs_dir / "runs" / run_tag / sample.sample_id / "trace.json"
        trace_out.parent.mkdir(parents=True, exist_ok=True)
        trace_out.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

        status_str = "PASS (7/7 gates)" if report.all_gates_passed else "PARTIAL/FAIL"
        print(
            f"  [{sample.sample_id}] {status_str} | items={report.verified_items_count}/{report.total_items_count} "
            f"| tests={len(cr.selected_tests)}/{cr.total_tests} | latency={inf.latency_ms} ms"
        )
        if not report.all_gates_passed:
            for g in report.gates:
                if not g.passed:
                    print(f"     -> {g.gate_id}: {g.violations}")

    mean_latency = round(
        sum(r["inference"]["latency_ms"] for r in sample_records) / max(len(sample_records), 1), 2
    )
    mean_caller_recall = round(
        sum(r["verification"]["caller_trace_recall"] for r in sample_records) / max(len(sample_records), 1), 4
    )
    mean_compression = round(
        sum(r["changeradar"]["compression_ratio"] for r in sample_records) / max(len(sample_records), 1), 4
    )

    first_inf = sample_records[0]["inference"]
    summary_bundle = {
        "project": "ReleaseGuard: Verifiable Upgrade Checklist & Breaking-Change Tracer",
        "track": "Developer tools",
        "is_dry_run": is_dry_run,
        "run_tag": run_tag,
        "model_id": first_inf["model_id"],
        "model_revision": first_inf["model_revision"],
        "skill_provenance": skill_prov.to_dict(),
        "environment": env.to_dict(),
        "passed_samples": passed_samples,
        "total_samples": len(sample_records),
        "verified_items_total": verified_items_total,
        "items_total": items_total,
        "mean_latency_ms": mean_latency,
        "mean_caller_recall": mean_caller_recall,
        "mean_test_compression": mean_compression,
        "samples": sample_records,
    }

    summary_file = outputs_dir / ("summary_dry_run.json" if is_dry_run else "summary.json")
    bundle_file = outputs_dir / ("run_bundle_dry_run.json" if is_dry_run else "run_bundle.json")
    serialized_bundle = json.dumps(summary_bundle, indent=2, ensure_ascii=False)
    summary_file.write_text(serialized_bundle, encoding="utf-8")
    bundle_file.write_text(serialized_bundle, encoding="utf-8")

    html_name = "walkthrough_dry_run.html" if is_dry_run else "walkthrough_report.html"
    html_path = generate_html_walkthrough(summary_bundle, outputs_dir / html_name)
    print(f"\nSaved run bundle JSON    : {bundle_file}")
    print(f"Saved summary JSON       : {summary_file}")
    print(f"Saved HTML Walkthrough   : {html_path}")

    if not is_dry_run:
        tpl_path = WORKSPACE_ROOT / "HF_DISCUSSION_TEMPLATE_READY.md"
        filled_path = fill_hf_discussion_template(
            tpl_path, summary_bundle, outputs_dir / "HF_DISCUSSION_FILLED.md"
        )
        print(f"Filled HF Discussion Doc : {filled_path}")
    else:
        print(
            "NOTE: `--dry-run` mode active -> `HF_DISCUSSION_FILLED.md` was intentionally NOT generated "
            "(run `--download-and-run` with local Spark-X2.6-4B to populate real inference logs)."
        )

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ReleaseGuard — Spark-X2.6-4B × SkillHub ChangeRadar Challenge Runner"
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-env", action="store_true", help="Inspect hardware, disk, cache & Spark-X2.6-4B sizes")
    mode.add_argument("--dry-run", action="store_true", help="Run offline pipeline check (watermarked dry-run)")
    mode.add_argument("--download-and-run", action="store_true", help="Run real local Spark-X2.6-4B inference")

    p.add_argument(
        "--backend",
        choices=["openai-compat", "transformers"],
        default="openai-compat",
        help="Local inference runtime for --download-and-run (default: openai-compat for llama.cpp/Ollama/vLLM)",
    )
    p.add_argument("--api-base", default="", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:8080/v1")
    p.add_argument("--served-model-name", default="spark2.6", help="Model name for OpenAI-compatible server")
    p.add_argument("--model-id", default=SPARK_HF_REPO, help="HF repo or local path for transformers backend")
    p.add_argument("--model-revision", default="", help="Override exact model revision SHA")
    p.add_argument("--download-gguf", action="store_true", help="Download official GGUF weight after confirmation")
    p.add_argument("--gguf-quant", choices=["Q4_K_M", "Q8_0"], default="Q4_K_M", help="GGUF quantization variant")
    p.add_argument("--thinking", choices=["none", "low", "high"], default="none", help="Spark thinking budget")
    p.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    p.add_argument("--max-tokens", type=int, default=2048, help="Max generated tokens")
    p.add_argument("--sample", default="", help="Optional sample prefix filter (e.g. S01)")
    p.add_argument("--resume", action="store_true", help="Reuse already-saved real trace.json files")
    p.add_argument("--yes", action="store_true", help="Confirm weight download size non-interactively")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    env = inspect_environment(WORKSPACE_ROOT)
    print_env_report(env)

    outputs_dir = WORKSPACE_ROOT / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "env_report.json").write_text(
        json.dumps(env.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if args.check_env:
        return 0
    if args.dry_run:
        return execute_pipeline(args, env, is_dry_run=True)
    return execute_pipeline(args, env, is_dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
