# -*- coding: utf-8 -*-
"""Comprehensive pytest suite for ReleaseGuard (Spark-X2.6-4B × SkillHub ChangeRadar)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

import run_challenge  # noqa: E402
from releaseguard.html_report import generate_html_walkthrough  # noqa: E402
from releaseguard.parser import (  # noqa: E402
    extract_code_and_flag_tokens,
    extract_numeric_and_version_tokens,
    load_all_samples,
    parse_release_notes,
    parse_unified_diff,
)
from releaseguard.prompts import build_spark_messages  # noqa: E402
from releaseguard.skill_bridge import (  # noqa: E402
    EXPECTED_FINGERPRINT,
    EXPECTED_SKILL_MD_SHA256,
    EXPECTED_SKILL_VERSION,
    run_changeradar_pipeline,
    verify_skillhub_package,
)
from releaseguard.spark_runner import (  # noqa: E402
    SPARK_GGUF_Q4_BYTES,
    SPARK_HF_REVISION,
    SPARK_HF_TOTAL_BYTES,
    DryRunPreviewRunner,
     inspect_environment,
    is_spark_model_list,
)
from releaseguard.template_filler import fill_hf_discussion_template  # noqa: E402
from releaseguard.verifier import (  # noqa: E402
    extract_json_and_thinking,
    verify_spark_output,
)

SKILL_DIR = WORKSPACE_ROOT / ".agents" / "skills" / "changeradar"
SAMPLES_DIR = WORKSPACE_ROOT / "data" / "samples"


@pytest.fixture(scope="module")
def skill_prov():
    return verify_skillhub_package(SKILL_DIR, run_self_checks=True)


@pytest.fixture(scope="module")
def all_samples():
    return load_all_samples(SAMPLES_DIR)


@pytest.fixture(scope="module")
def cr_by_id(all_samples):
    return {
        s.sample_id: run_changeradar_pipeline(SKILL_DIR, s.repo_dir, s.patch_diff_raw)
        for s in all_samples
    }


def test_curated_samples_count_and_structure(all_samples):
    assert len(all_samples) == 5
    ids = [s.sample_id for s in all_samples]
    assert ids == [
        "S01_httpx_0280",
        "S02_fastapi_01150",
        "S03_pydantic_2100",
        "S04_click_820",
        "S05_requests_2322",
    ]
    for s in all_samples:
        assert len(s.release_lines) == 4
        assert len(s.diff_files) == 2
        assert s.repo_dir.is_dir()
        assert (s.repo_dir / "tests").is_dir()


def test_release_note_and_diff_parsers():
    md = "# Title\n- Breaking: Removed `foo` in `1.2.0`.\n- Added `--fast-mode` flag.\n"
    lines = parse_release_notes(md)
    assert [ln.line_id for ln in lines] == ["RN-1", "RN-2"]
    assert "Removed `foo`" in lines[0].text

    nums = extract_numeric_and_version_tokens("Upgrade v2.10.0 speed 18% offset +00:00 limit 100")
    assert {"v2.10.0", "18%", "+00:00", "100"} <= nums

    flags = extract_code_and_flag_tokens("Use `--strict-tls` for CVE-2024-35195 and `proxy=...`")
    assert {"--strict-tls", "CVE-2024-35195", "proxy=..."} <= flags


def test_parse_unified_diff_extracts_added_and_removed_lines(all_samples):
    s01 = all_samples[0]
    files = parse_unified_diff(s01.patch_diff_raw)
    paths = [f.file_path for f in files]
    assert paths == ["http_client/config.py", "http_client/transport.py"]
    transport_diff = files[1]
    assert any("proxies=None" in ln for ln in transport_diff.removed_lines)
    assert any("proxy=None" in ln for ln in transport_diff.added_lines)


def test_skillhub_changeradar_provenance_and_sha256(skill_prov):
    assert skill_prov.namespace == "global"
    assert skill_prov.slug == "changeradar"
    assert skill_prov.version == EXPECTED_SKILL_VERSION
    assert skill_prov.fingerprint == EXPECTED_FINGERPRINT
    assert skill_prov.skill_md_sha256 == EXPECTED_SKILL_MD_SHA256
    assert skill_prov.files_verified == 44
    assert skill_prov.self_checks_passed is True


@pytest.mark.parametrize("sample_idx", [0, 1, 2, 3, 4])
def test_changeradar_ast_pipeline_matches_ground_truth(all_samples, cr_by_id, sample_idx):
    sample = all_samples[sample_idx]
    cr = cr_by_id[sample.sample_id]
    gt = sample.ground_truth

    assert set(cr.changed_files) == set(gt["expected_changed_files"])
    assert set(cr.seed_nodes) == set(gt["expected_seed_nodes"])
    assert set(gt["expected_affected_callers"]) <= set(cr.affected_callers)

    selected_names = {t["test_name"] for t in cr.selected_tests}
    assert selected_names == set(gt["expected_selected_tests"])
    assert not (selected_names & set(gt["excluded_unrelated_tests"]))
    assert cr.total_tests == 3
    assert cr.compression_ratio == pytest.approx(0.667, abs=0.01)


def test_prompt_builder_embeds_skill_redlines_and_machine_json(all_samples, skill_prov, cr_by_id):
    s01 = all_samples[0]
    cr = cr_by_id[s01.sample_id]
    msgs = build_spark_messages(s01, skill_prov, cr)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "global/changeradar" in msgs[0]["content"]
    assert "NEVER invent call-graph node IDs" in msgs[0]["content"]
    assert "[RN-1]" in msgs[1]["content"]
    assert "http_client/transport.py::ClientSession::open_connection" in msgs[1]["content"]


def test_extract_json_and_thinking_handles_think_tags_and_fences():
    raw = '<think>\nChecking RN-1 against diff...\n</think>\n```json\n{"step0": {"schema_version": "1.0"}, "items": []}\n```'
    parsed, thinking, err = extract_json_and_thinking(raw)
    assert err is None
    assert thinking == "Checking RN-1 against diff..."
    assert parsed["step0"]["schema_version"] == "1.0"


def _make_valid_payload(sample, cr):
    runner = DryRunPreviewRunner()
    inf = runner.generate([], sample, cr)
    return json.loads(inf.raw_text)


def test_verifier_passes_valid_grounded_output_across_all_samples(all_samples, cr_by_id):
    for s in all_samples:
        cr = cr_by_id[s.sample_id]
        payload = _make_valid_payload(s, cr)
        _, _, _, rep = verify_spark_output(json.dumps(payload), s, cr)
        assert rep.all_gates_passed is True, f"Failed on {s.sample_id}: {[g.violations for g in rep.gates if not g.passed]}"


def test_verifier_gate_g2_blocks_cross_line_and_paraphrased_quotes(all_samples, cr_by_id):
    s01 = all_samples[0]
    cr = cr_by_id[s01.sample_id]
    payload = _make_valid_payload(s01, cr)
    payload["items"][0]["verbatim_quote"] = "Completely paraphrased quote that does not exist in RN-1 at all"
    payload["items"][1]["verbatim_quote"] = "Deprecated boolean/string\nPreserved default connection"

    _, _, _, rep = verify_spark_output(json.dumps(payload), s01, cr)
    g2 = next(g for g in rep.gates if g.gate_id == "G2")
    assert g2.passed is False
    assert len(g2.violations) == 2


def test_verifier_gate_g3_blocks_invented_version_and_cli_flag(all_samples, cr_by_id):
    s01 = all_samples[0]
    cr = cr_by_id[s01.sample_id]
    payload = _make_valid_payload(s01, cr)
    payload["items"][0]["action"] = "Upgrade to 0.99.4 and pass --magic-nonexistent-flag on port 9876."
    payload["items"][0]["version_or_flag_tokens"].append("--magic-nonexistent-flag")

    _, _, _, rep = verify_spark_output(json.dumps(payload), s01, cr)
    g3 = next(g for g in rep.gates if g.gate_id == "G3")
    assert g3.passed is False
    assert any("0.99.4" in v for v in g3.violations)
    assert any("--magic-nonexistent-flag" in v for v in g3.violations)


def test_verifier_gate_g4_and_g5_block_hallucinated_callgraph_nodes_and_tests(all_samples, cr_by_id):
    s01 = all_samples[0]
    cr = cr_by_id[s01.sample_id]
    payload = _make_valid_payload(s01, cr)
    payload["items"][0]["traced_change"]["changed_symbol"] = "http_client/fake.py::invented_seed"
    payload["items"][0]["traced_change"]["affected_features"].append("services/billing.py::invented_caller")
    payload["items"][0]["traced_change"]["recommended_tests"].append("test_compute_backoff_delay")  # unrelated excluded test!

    _, _, _, rep = verify_spark_output(json.dumps(payload), s01, cr)
    g4 = next(g for g in rep.gates if g.gate_id == "G4")
    g5 = next(g for g in rep.gates if g.gate_id == "G5")
    assert g4.passed is False
    assert g5.passed is False
    assert any("invented_caller" in v for v in g5.violations)
    assert any("test_compute_backoff_delay" in v for v in g5.violations)


def test_verifier_gate_g6_blocks_false_breaking_and_invented_owner_or_date(all_samples, cr_by_id):
    s02 = all_samples[1]  # FastAPI 0.115.0 with RN-4 no-owner/no-date note
    cr = cr_by_id[s02.sample_id]
    payload = copy.deepcopy(_make_valid_payload(s02, cr))
    # Flip additive RN-3 to breaking=True and invent owner + date on RN-4
    payload["items"][2]["breaking"] = True
    payload["items"][3]["action"] = "Assigned to @alice_dev for 2026-12-15 release."
    payload["items"][3]["uncertainty_note"] = None

    _, _, _, rep = verify_spark_output(json.dumps(payload), s02, cr)
    g6 = next(g for g in rep.gates if g.gate_id == "G6")
    assert g6.passed is False
    assert len(g6.violations) >= 3


def test_html_walkthrough_generator_and_anti_fabrication_template_guard(tmp_path, all_samples, skill_prov, cr_by_id):
    s01 = all_samples[0]
    cr = cr_by_id[s01.sample_id]
    inf = DryRunPreviewRunner().generate([], s01, cr)
    items, step0, thinking, rep = verify_spark_output(inf.raw_text, s01, cr)

    dry_bundle = {
        "is_dry_run": True,
        "model_id": inf.model_id,
        "model_revision": inf.model_revision,
        "skill_provenance": skill_prov.to_dict(),
        "environment": {"os_platform": "Windows", "cpu_model": "Test CPU", "logical_cores": 4, "ram_total_gib": 16.0},
        "passed_samples": 1,
        "verified_items_total": 4,
        "items_total": 4,
        "mean_latency_ms": 1.2,
        "mean_caller_recall": 1.0,
        "mean_test_compression": 0.667,
        "samples": [
            {
                "sample_id": s01.sample_id,
                "project": s01.project,
                "from_version": s01.from_version,
                "to_version": s01.to_version,
                "release_url": s01.release_url,
                "license": s01.license,
                "release_lines": [{"line_id": l.line_id, "line_num": l.line_num, "text": l.text} for l in s01.release_lines],
                "patch_diff_raw": s01.patch_diff_raw,
                "ground_truth": s01.ground_truth,
                "changeradar": cr.to_dict(),
                "prompt_messages": [],
                "inference": inf.to_dict(),
                "step0_contract": step0,
                "thinking_trace": thinking,
                "checklist_items": [it.to_dict() for it in items],
                "verification": rep.to_dict(),
            }
        ],
    }

    html_out = generate_html_walkthrough(dry_bundle, tmp_path / "walkthrough.html")
    html_text = html_out.read_text(encoding="utf-8")
    assert "DRY-RUN PIPELINE PREVIEW" in html_text
    assert "Approved: 0 of 0" in html_text
    assert "S01_httpx_0280" in html_text

    # Anti-fabrication guard MUST reject dry_bundle
    tpl = WORKSPACE_ROOT / "HF_DISCUSSION_TEMPLATE_READY.md"
    with pytest.raises(ValueError, match="Refusing to populate"):
        fill_hf_discussion_template(tpl, dry_bundle, tmp_path / "filled.md")

    # When a non-dry-run bundle from a real runner is supplied, slots are populated cleanly
    real_bundle = copy.deepcopy(dry_bundle)
    real_bundle["is_dry_run"] = False
    real_bundle["model_id"] = "XHToken/Spark-X2.6-4B-GGUF"
    real_bundle["model_revision"] = "9d716770ac7477776de5f891f70cdf98b003a5cd"
    real_bundle["samples"][0]["inference"]["is_dry_run"] = False
    real_bundle["samples"][0]["inference"]["backend"] = "openai_compat (http://127.0.0.1:8080/v1)"
    filled = fill_hf_discussion_template(tpl, real_bundle, tmp_path / "filled.md")
    filled_text = filled.read_text(encoding="utf-8")
    assert "{{SPARK_" not in filled_text
    assert "9d716770ac7477776de5f891f70cdf98b003a5cd" in filled_text


def test_spark_model_list_guard_blocks_non_spark_proxies():
    assert is_spark_model_list(["gemini-4-carbon-high", "claude-sonnet-4-6"]) is False
    assert is_spark_model_list(["SparkLLM/Spark-X2.6-4B"]) is True
    assert is_spark_model_list(["spark2.6"]) is True


def test_cli_check_env_and_dry_run():
    env = inspect_environment(WORKSPACE_ROOT)
    assert env.models_catalog["transformers_bf16"]["total_bytes"] == SPARK_HF_TOTAL_BYTES
    assert env.models_catalog["transformers_bf16"]["revision_sha"] == SPARK_HF_REVISION
    assert env.models_catalog["gguf_q4_k_m"]["total_bytes"] == SPARK_GGUF_Q4_BYTES

    filled_md = WORKSPACE_ROOT / "outputs" / "HF_DISCUSSION_FILLED.md"
    before_bytes = filled_md.read_bytes() if filled_md.exists() else None

    assert run_challenge.main(["--check-env"]) == 0
    assert run_challenge.main(["--dry-run"]) == 0
    assert (WORKSPACE_ROOT / "outputs" / "summary_dry_run.json").exists()
    assert (WORKSPACE_ROOT / "outputs" / "walkthrough_dry_run.html").exists()
    if before_bytes is None:
        assert not filled_md.exists()
    else:
        assert filled_md.read_bytes() == before_bytes
