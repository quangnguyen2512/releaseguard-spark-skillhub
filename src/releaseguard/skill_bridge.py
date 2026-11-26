# -*- coding: utf-8 -*-
"""Bridge to the installed SkillHub `global/changeradar` skill package.

1. Verifies `.skillhub/metadata.json` provenance and exact SHA-256 checksums of all package files.
2. Executes Step 0.5 `--self-check` across all 6 bundled deterministic scripts.
3. Runs Steps 1–5 (`cache.py` -> `callgraph.py` -> `diffparse.py` -> `propagate.py` -> `testselect.py`)
   over a target repository and unified `git diff`, returning machine-verified JSON envelopes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from releaseguard.models import ChangeradarResult, SkillProvenance

EXPECTED_SKILL_SLUG = "changeradar"
EXPECTED_SKILL_VERSION = "20260809.064909"
EXPECTED_FINGERPRINT = "sha256:4fb641ead1b8fe8b43d57a83c828627fbfb152396d9cf9952aa9851619d27a4a"
EXPECTED_SKILL_MD_SHA256 = "920761b5d7008bbf30c925a41bd9c5ae3ff3be18f865ed1d071108e826f3b843"

SCRIPT_NAMES = [
    "cache.py",
    "callgraph.py",
    "diffparse.py",
    "propagate.py",
    "testselect.py",
    "stacktrace.py",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_skillhub_package(skill_dir: Path, run_self_checks: bool = True) -> SkillProvenance:
    """Verify the installed SkillHub `global/changeradar` package integrity and optional script self-checks."""
    meta_path = skill_dir / ".skillhub" / "metadata.json"
    skill_md_path = skill_dir / "SKILL.md"
    if not meta_path.exists() or not skill_md_path.exists():
        raise FileNotFoundError(
            f"SkillHub package missing at {skill_dir}. Run: "
            "npx @astron-team/skillhub@latest install global/changeradar --dir .agents/skills"
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files_map: dict[str, str] = meta.get("files", {})
    if not files_map:
        raise ValueError("SkillHub metadata.json contains an empty files checksum map.")

    for rel_path, expected_hash in files_map.items():
        fp = skill_dir / rel_path
        if not fp.exists():
            raise FileNotFoundError(f"SkillHub file missing: {fp}")
        actual_hash = _sha256_file(fp)
        if actual_hash != expected_hash:
            raise ValueError(
                f"SHA-256 mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
            )

    skill_md_sha = _sha256_file(skill_md_path)
    self_checks_ok = False
    if run_self_checks:
        scripts_dir = skill_dir / "scripts"
        for sname in SCRIPT_NAMES:
            proc = subprocess.run(
                [sys.executable, str(scripts_dir / sname), "--self-check"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"changeradar {sname} --self-check failed: {proc.stderr or proc.stdout}")
            payload = json.loads(proc.stdout)
            if payload.get("schema_version") != "1.0" or payload.get("status") != "ok":
                raise RuntimeError(f"changeradar {sname} invalid envelope: {payload}")
        self_checks_ok = True

    namespace = meta.get("namespace", "global")
    slug = meta.get("slug", EXPECTED_SKILL_SLUG)
    registry = meta.get("registry", "https://skill.xfyun.cn").rstrip("/")
    return SkillProvenance(
        registry=registry,
        namespace=namespace,
        slug=slug,
        version=meta.get("version", EXPECTED_SKILL_VERSION),
        version_id=int(meta.get("versionId", 0)),
        fingerprint=meta.get("fingerprint", ""),
        skill_md_sha256=skill_md_sha,
        detail_url=f"{registry}/space/{namespace}/{slug}",
        skill_dir=str(skill_dir),
        files_verified=len(files_map),
        self_checks_passed=self_checks_ok,
    )


def _run_script_json(script_path: Path, args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"{script_path.name} exited with error code {proc.returncode}: {proc.stdout} {proc.stderr}"
        )
    payload = json.loads(proc.stdout)
    if payload.get("schema_version") != "1.0":
        raise ValueError(f"Unexpected schema_version from {script_path.name}: {payload}")
    return payload


def run_changeradar_pipeline(skill_dir: Path, repo_dir: Path, patch_diff_text: str) -> ChangeradarResult:
    """Execute Steps 1–5 of `changeradar` (`cache -> callgraph -> diffparse -> propagate -> testselect`)."""
    scripts_dir = skill_dir / "scripts"
    tests_dir = repo_dir / "tests"

    with tempfile.TemporaryDirectory(prefix="rg_cr_") as tmp:
        tmp_path = Path(tmp)
        cache_dir = tmp_path / ".cr_cache"
        diff_file = tmp_path / "patch.diff"
        graph_file = tmp_path / "callgraph.json"
        changes_file = tmp_path / "diffparse.json"
        prop_file = tmp_path / "propagate.json"

        diff_file.write_text(patch_diff_text, encoding="utf-8", newline="\n")

        # Step 1: cache.py
        cache_env = _run_script_json(
            scripts_dir / "cache.py",
            ["--root", str(repo_dir), "--cache-dir", str(cache_dir)],
        )

        # Step 2: callgraph.py
        graph_env = _run_script_json(
            scripts_dir / "callgraph.py",
            ["--root", str(repo_dir)],
        )
        graph_file.write_text(json.dumps(graph_env, ensure_ascii=False), encoding="utf-8")

        # Step 3: diffparse.py (--graph is mandatory per SKILL.md Step 3)
        diff_env = _run_script_json(
            scripts_dir / "diffparse.py",
            ["--diff", str(diff_file), "--graph", str(graph_file)],
        )
        changes_file.write_text(json.dumps(diff_env, ensure_ascii=False), encoding="utf-8")

        # Step 4: propagate.py
        prop_env = _run_script_json(
            scripts_dir / "propagate.py",
            ["--graph", str(graph_file), "--changes", str(changes_file)],
        )
        prop_file.write_text(json.dumps(prop_env, ensure_ascii=False), encoding="utf-8")

        # Step 5: testselect.py
        test_env = _run_script_json(
            scripts_dir / "testselect.py",
            ["--impact", str(prop_file), "--graph", str(graph_file), "--tests", str(tests_dir)],
        )

    diff_data = diff_env.get("data", {})
    prop_data = prop_env.get("data", {})
    test_data = test_env.get("data", {})

    changed_files = [c["file"] for c in diff_data.get("changes", []) if c.get("file")]
    seed_nodes = list(prop_data.get("seeds", []))
    impact_entries = prop_data.get("impact", [])
    all_impact_nodes = [entry["node_id"] for entry in impact_entries if entry.get("node_id")]
    affected_callers = [
        entry["node_id"]
        for entry in impact_entries
        if entry.get("node_id") and int(entry.get("distance", 0)) >= 1 and not entry.get("is_seed", False)
    ]
    selected_tests = list(test_data.get("tests", []))
    metrics = test_data.get("metrics", {})

    return ChangeradarResult(
        cache=cache_env,
        callgraph=graph_env,
        diffparse=diff_env,
        propagate=prop_env,
        testselect=test_env,
        changed_files=changed_files,
        seed_nodes=seed_nodes,
        affected_callers=affected_callers,
        all_impact_nodes=all_impact_nodes,
        selected_tests=selected_tests,
        total_tests=int(metrics.get("total_tests", 0)),
        compression_ratio=float(metrics.get("compression_ratio", 0.0)),
        impact_coverage=float(metrics.get("impact_coverage", 0.0)),
    )
