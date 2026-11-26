# -*- coding: utf-8 -*-
"""7-Gate Deterministic Ground-Truth Citation & Hallucination Verifier.

Audits every checklist item emitted by `Spark-X2.6-4B` against:
1. The raw numbered release notes (`RN-1..RN-N`)
2. The unified `git diff` (`patch.diff`)
3. SkillHub `global/changeradar` deterministic AST call-graph, blast-radius, and test-selection JSON
4. Pre-committed sample acceptance criteria (`ground_truth.json`)
"""
from __future__ import annotations

import json
import re
from typing import Any

from releaseguard.models import (
    ChangeradarResult,
    ChecklistItem,
    GateResult,
    ReleaseSample,
    VerificationReport,
)
from releaseguard.parser import (
    extract_code_and_flag_tokens,
    extract_numeric_and_version_tokens,
)

THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
FENCE_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
INVENTED_DATE_RE = re.compile(r"\b202[4-9]-\d{2}-\d{2}\b|\bQ[1-4]\s*202[4-9]\b")
INVENTED_OWNER_RE = re.compile(r"@[A-Za-z0-9_-]{2,}|\bassigned to [A-Z][a-z]+", re.IGNORECASE)

VALID_SEVERITIES = {"breaking", "behavior_change", "deprecation", "additive"}

NON_BREAKING_CUE_PHRASES = (
    "unchanged",
    "without changing",
    "without altering",
    "disabled by default",
    "docstrings",
    "future note:",
    "scheduled for removal in",
    "byte-identical",
)


def extract_json_and_thinking(raw_response: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Separate optional `<think>...</think>` trace and parse the JSON payload."""
    thinking_parts = [m.group(1).strip() for m in THINK_BLOCK_RE.finditer(raw_response)]
    thinking_text = "\n\n".join(p for p in thinking_parts if p)
    cleaned = THINK_BLOCK_RE.sub("", raw_response).strip()

    fence_match = FENCE_JSON_RE.search(cleaned)
    candidate = fence_match.group(1).strip() if fence_match else cleaned
    if not candidate.startswith("{"):
        first_brace = candidate.find("{")
        last_brace = candidate.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = candidate[first_brace : last_brace + 1]

    try:
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            return None, thinking_text, "Top-level JSON value must be an object."
        return parsed, thinking_text, None
    except Exception as exc:
        return None, thinking_text, f"Invalid JSON response: {exc}"


def _build_allowed_numeric_tokens(sample: ReleaseSample, cr_result: ChangeradarResult) -> set[str]:
    corpus = "\n".join(
        [
            sample.release_notes_raw,
            sample.patch_diff_raw,
            sample.from_version,
            sample.to_version,
            json.dumps(cr_result.testselect.get("data", {}).get("metrics", {})),
        ]
    )
    allowed = extract_numeric_and_version_tokens(corpus)
    # Allow stripped leading 'v' equivalence (e.g. v2.10.0 <-> 2.10.0) and small ordinals 0/1/2
    expanded = set(allowed)
    for tok in list(allowed):
        if tok.startswith("v") and len(tok) > 1 and tok[1].isdigit():
            expanded.add(tok[1:])
        elif tok and tok[0].isdigit() and "." in tok:
            expanded.add(f"v{tok}")
    expanded.update({"0", "1", "2"})
    return expanded


def _build_allowed_code_tokens(sample: ReleaseSample, cr_result: ChangeradarResult) -> set[str]:
    corpus_parts = [
        sample.release_notes_raw,
        sample.patch_diff_raw,
        sample.project,
        sample.from_version,
        sample.to_version,
        *cr_result.changed_files,
        *cr_result.all_impact_nodes,
        *(t["test_name"] for t in cr_result.selected_tests),
        *(t["test_file"] for t in cr_result.selected_tests),
    ]
    full_text = "\n".join(corpus_parts)
    tokens = extract_code_and_flag_tokens(full_text)
    return tokens, full_text


def verify_spark_output(
    raw_response: str,
    sample: ReleaseSample,
    cr_result: ChangeradarResult,
) -> tuple[list[ChecklistItem], dict[str, Any] | None, str, VerificationReport]:
    """Run all 7 deterministic verification gates on a `Spark-X2.6-4B` response."""
    parsed, thinking_text, parse_err = extract_json_and_thinking(raw_response)
    gates: list[GateResult] = []

    if parsed is None:
        g1 = GateResult(
            gate_id="G1",
            name="Schema & Step-0 Contract Gate",
            passed=False,
            summary="Failed to parse valid JSON object from model output.",
            violations=[parse_err or "Unknown JSON parse error"],
        )
        empty_report = VerificationReport(
            sample_id=sample.sample_id,
            all_gates_passed=False,
            gates=[g1],
            verified_items_count=0,
            total_items_count=0,
            breaking_precision_match=False,
            seed_trace_recall=0.0,
            caller_trace_recall=0.0,
            test_selection_exact=False,
        )
        return [], None, thinking_text, empty_report

    # ---- Gate G1: Schema & Step-0 Contract Gate ----
    g1_violations: list[str] = []
    step0 = parsed.get("step0")
    if not isinstance(step0, dict):
        g1_violations.append("Missing or non-object `step0` understanding envelope.")
    else:
        if step0.get("schema_version") != "1.0":
            g1_violations.append(f"step0.schema_version must be '1.0', got {step0.get('schema_version')!r}")
        if step0.get("mode") != "diff":
            g1_violations.append(f"step0.mode must be 'diff', got {step0.get('mode')!r}")
        if step0.get("confidence") not in ("high", "low"):
            g1_violations.append(f"step0.confidence invalid: {step0.get('confidence')!r}")
        if not isinstance(step0.get("target"), dict) or not step0["target"].get("path"):
            g1_violations.append("step0.target.path is required per changeradar SKILL.md §2.")

    raw_items = parsed.get("items")
    items: list[ChecklistItem] = []
    if not isinstance(raw_items, list) or not raw_items:
        g1_violations.append("`items` must be a non-empty list of checklist objects.")
    else:
        seen_ids: set[str] = set()
        for idx, raw_it in enumerate(raw_items):
            if not isinstance(raw_it, dict):
                g1_violations.append(f"items[{idx}] is not an object.")
                continue
            item = ChecklistItem.from_dict(raw_it)
            if not item.id or item.id in seen_ids:
                g1_violations.append(f"Duplicate or missing item.id at index {idx}: {item.id!r}")
            seen_ids.add(item.id)
            if item.severity not in VALID_SEVERITIES:
                g1_violations.append(f"{item.id}: invalid severity {item.severity!r}")
            if not isinstance(raw_it.get("breaking"), bool):
                g1_violations.append(f"{item.id}: `breaking` must be a boolean.")
            items.append(item)

    gates.append(
        GateResult(
            gate_id="G1",
            name="Schema & Step-0 Contract Gate",
            passed=len(g1_violations) == 0,
            summary=f"Validated Step-0 contract and {len(items)} checklist item(s)."
            if not g1_violations
            else f"{len(g1_violations)} schema/contract violation(s).",
            violations=g1_violations,
        )
    )

    # ---- Gate G2: Verbatim Single-Line Release-Note Quote Gate ----
    rn_map = {ln.line_id: ln.text for ln in sample.release_lines}
    g2_violations: list[str] = []
    used_rn_ids: set[str] = set()
    for item in items:
        lid = item.release_note_line_id
        if lid not in rn_map:
            g2_violations.append(f"{item.id}: unknown release_note_line_id {lid!r}")
            continue
        if lid in used_rn_ids:
            g2_violations.append(f"{item.id}: duplicate checklist item for {lid}")
        used_rn_ids.add(lid)
        q = item.verbatim_quote.strip()
        if len(q) < 15:
            g2_violations.append(f"{item.id}: verbatim_quote too short (<15 chars): {q!r}")
        elif "\n" in q or "\r" in q:
            g2_violations.append(f"{item.id}: cross-line quote forbidden in {lid}")
        elif q not in rn_map[lid]:
            # Also tolerate stripping backticks if model omitted markdown backticks around symbols
            plain_source = rn_map[lid].replace("`", "")
            plain_quote = q.replace("`", "")
            if plain_quote not in plain_source:
                g2_violations.append(
                    f"{item.id}: verbatim_quote is NOT an exact substring of [{lid}]: {q!r}"
                )

    gates.append(
        GateResult(
            gate_id="G2",
            name="Verbatim Release-Note Quote Gate",
            passed=len(g2_violations) == 0,
            summary=f"{len(items) - len(g2_violations)}/{len(items)} quotes verified verbatim against single source lines."
            if items
            else "No items to verify.",
            violations=g2_violations,
        )
    )

    # ---- Gate G3: Zero-Invented Version, Number & Flag Gate ----
    allowed_nums = _build_allowed_numeric_tokens(sample, cr_result)
    _, full_source_corpus = _build_allowed_code_tokens(sample, cr_result)
    plain_corpus_lower = full_source_corpus.replace("`", "").lower()
    g3_violations: list[str] = []

    for item in items:
        # Remove structural IDs like CHK-1 / RN-1 before scanning numbers
        text_to_scan = f"{item.title} {item.action} {' '.join(item.version_or_flag_tokens)}"
        text_to_scan = re.sub(r"\b(?:CHK|RN)-\d+\b", "", text_to_scan)
        nums = extract_numeric_and_version_tokens(text_to_scan)
        for num in sorted(nums):
            if num not in allowed_nums and num not in full_source_corpus:
                g3_violations.append(f"{item.id}: invented number/version token {num!r} not in source/diff")

        for tok in item.version_or_flag_tokens:
            clean_tok = tok.strip().strip("`")
            if clean_tok and clean_tok.lower() not in plain_corpus_lower:
                g3_violations.append(
                    f"{item.id}: version_or_flag_token {tok!r} does not appear in release notes or git diff"
                )

        inline_flags = extract_code_and_flag_tokens(f"{item.title} {item.action}")
        for flag in sorted(inline_flags):
            clean_flag = flag.strip("`")
            if clean_flag.startswith("--") or clean_flag.startswith("CVE-"):
                if clean_flag.lower() not in plain_corpus_lower:
                    g3_violations.append(f"{item.id}: invented CLI flag or CVE {clean_flag!r}")

    gates.append(
        GateResult(
            gate_id="G3",
            name="Zero-Invented Version, Number & Flag Gate",
            passed=len(g3_violations) == 0,
            summary="All version numbers, metrics, CVEs, and flags grounded in source/diff."
            if not g3_violations
            else f"{len(g3_violations)} ungrounded token(s) detected.",
            violations=g3_violations,
        )
    )

    # ---- Gate G4: Diff File & Seed Symbol Grounding Gate ----
    g4_violations: list[str] = []
    valid_files = set(cr_result.changed_files)
    valid_seeds = set(cr_result.seed_nodes)
    resolved_seeds_traced: set[str] = set()

    for item in items:
        tc = item.traced_change
        if tc.changed_file is not None:
            if tc.changed_file not in valid_files:
                g4_violations.append(
                    f"{item.id}: changed_file {tc.changed_file!r} not in diffparse changed_files {sorted(valid_files)}"
                )
        if tc.changed_symbol is not None:
            qualified_candidate = f"{tc.changed_file}::{tc.changed_symbol}" if tc.changed_file else ""
            if tc.changed_symbol in valid_seeds:
                resolved_seeds_traced.add(tc.changed_symbol)
            elif qualified_candidate in valid_seeds:
                tc.changed_symbol = qualified_candidate
                resolved_seeds_traced.add(qualified_candidate)
            else:
                g4_violations.append(
                    f"{item.id}: changed_symbol {tc.changed_symbol!r} not in changeradar seeds {sorted(valid_seeds)}"
                )

    if items and not resolved_seeds_traced:
        g4_violations.append("No checklist item traced back to a concrete diff seed symbol.")

    gates.append(
        GateResult(
            gate_id="G4",
            name="Diff File & Seed Symbol Grounding Gate",
            passed=len(g4_violations) == 0,
            summary="Every traced file and changed symbol matches `diffparse.py` / `propagate.py` seeds."
            if not g4_violations
            else f"{len(g4_violations)} diff/seed grounding error(s).",
            violations=g4_violations,
        )
    )

    # ---- Gate G5: ChangeRadar Call-Graph & Test-Selection Red-Line Gate ----
    g5_violations: list[str] = []
    valid_impact = set(cr_result.all_impact_nodes) | set(cr_result.affected_callers)
    valid_tests = {t["test_name"] for t in cr_result.selected_tests} | {
        f"{t['test_file']}::{t['test_name']}" for t in cr_result.selected_tests
    }

    for item in items:
        tc = item.traced_change
        for feat in tc.affected_features:
            if feat not in valid_impact:
                g5_violations.append(
                    f"{item.id}: hallucinated affected_feature {feat!r} (violates changeradar Red Line #1)"
                )
        for tst in tc.recommended_tests:
            if tst not in valid_tests:
                g5_violations.append(
                    f"{item.id}: hallucinated or unselected test {tst!r} (violates changeradar Red Line #2)"
                )

    gates.append(
        GateResult(
            gate_id="G5",
            name="ChangeRadar Call-Graph & Test Red-Line Gate",
            passed=len(g5_violations) == 0,
            summary="100% of traced downstream callers and regression tests verified against `changeradar` AST JSON."
            if not g5_violations
            else f"{len(g5_violations)} call-graph/test hallucination(s) blocked.",
            violations=g5_violations,
        )
    )

    # ---- Gate G6: Breaking Polarity & Uncertainty Preservation Gate ----
    g6_violations: list[str] = []
    for item in items:
        src_line = rn_map.get(item.release_note_line_id, "")
        src_lower = src_line.lower()
        explicitly_breaking = src_lower.startswith("breaking") or "removed the deprecated" in src_lower
        if not explicitly_breaking and any(cue in src_lower for cue in NON_BREAKING_CUE_PHRASES):
            if item.breaking:
                g6_violations.append(
                    f"{item.id} ({item.release_note_line_id}): falsely marked breaking=true on non-breaking/unchanged/future line."
                )

        if "no owner" in src_lower or "no target release date" in src_lower or "future discussion" in src_lower:
            combined_out = f"{item.title} {item.action} {item.uncertainty_note or ''}"
            if INVENTED_DATE_RE.search(combined_out):
                g6_violations.append(
                    f"{item.id}: invented specific date/quarter on an unscheduled item."
                )
            if INVENTED_OWNER_RE.search(combined_out):
                g6_violations.append(
                    f"{item.id}: invented owner handle/assignee when source states no owner is set."
                )
            if not item.uncertainty_note:
                g6_violations.append(
                    f"{item.id}: missing explicit `uncertainty_note` for unscheduled/no-owner item ({item.release_note_line_id})."
                )

    gates.append(
        GateResult(
            gate_id="G6",
            name="Breaking Polarity & Uncertainty Preservation Gate",
            passed=len(g6_violations) == 0,
            summary="Breaking polarity and unscheduled-item uncertainty preserved accurately."
            if not g6_violations
            else f"{len(g6_violations)} polarity/uncertainty violation(s).",
            violations=g6_violations,
        )
    )

    # ---- Gate G7: Pre-Committed Acceptance Criteria Scorer ----
    gt = sample.ground_truth
    expected_breaking = set(gt.get("expected_breaking_line_ids", []))
    non_breaking_traps = set(gt.get("non_breaking_trap_line_ids", []))
    actual_breaking = {it.release_note_line_id for it in items if it.breaking}

    g7_violations: list[str] = []
    if expected_breaking != actual_breaking:
        g7_violations.append(
            f"Breaking line IDs mismatch: expected {sorted(expected_breaking)}, got {sorted(actual_breaking)}"
        )
    false_trap_hits = actual_breaking & non_breaking_traps
    if false_trap_hits:
        g7_violations.append(f"Non-breaking trap lines falsely marked breaking: {sorted(false_trap_hits)}")

    expected_seeds = set(gt.get("expected_seed_nodes", []))
    traced_seeds = resolved_seeds_traced
    seed_recall = round(len(expected_seeds & traced_seeds) / len(expected_seeds), 3) if expected_seeds else 1.0
    if seed_recall < 1.0:
        g7_violations.append(
            f"Incomplete seed symbol trace: expected {sorted(expected_seeds)}, traced {sorted(traced_seeds)}"
        )

    expected_callers = set(gt.get("expected_affected_callers", []))
    traced_callers = {feat for it in items for feat in it.traced_change.affected_features}
    caller_recall = (
        round(len(expected_callers & traced_callers) / len(expected_callers), 3) if expected_callers else 1.0
    )
    if caller_recall < 1.0:
        g7_violations.append(
            f"Incomplete downstream caller trace: expected {sorted(expected_callers)}, traced {sorted(traced_callers)}"
        )

    expected_tests = set(gt.get("expected_selected_tests", []))
    excluded_tests = set(gt.get("excluded_unrelated_tests", []))
    traced_tests = {
        tst.split("::")[-1] for it in items for tst in it.traced_change.recommended_tests
    }
    test_exact = (expected_tests <= traced_tests) and not (traced_tests & excluded_tests)
    if not test_exact:
        g7_violations.append(
            f"Test trace mismatch: expected {sorted(expected_tests)} (excluding {sorted(excluded_tests)}), got {sorted(traced_tests)}"
        )

    all_out_text = json.dumps([it.to_dict() for it in items], ensure_ascii=False).lower()
    for req_tok in gt.get("must_include_tokens", []):
        if req_tok.lower() not in all_out_text:
            g7_violations.append(f"Missing required acceptance token {req_tok!r} in checklist output.")

    gates.append(
        GateResult(
            gate_id="G7",
            name="Pre-Committed Gold Acceptance Criteria Gate",
            passed=len(g7_violations) == 0,
            summary=(
                f"Breaking match={expected_breaking == actual_breaking}, "
                f"seed_recall={seed_recall:.0%}, caller_recall={caller_recall:.0%}, test_exact={test_exact}."
            ),
            violations=g7_violations,
        )
    )

    all_passed = all(g.passed for g in gates)
    # Count items without per-item violations in G2-G6
    violated_prefixes = {
        v.split(":", 1)[0].split(" ", 1)[0]
        for g in gates[1:6]
        for v in g.violations
        if v.startswith("CHK-")
    }
    verified_count = sum(1 for it in items if it.id not in violated_prefixes) if parsed else 0

    report = VerificationReport(
        sample_id=sample.sample_id,
        all_gates_passed=all_passed,
        gates=gates,
        verified_items_count=verified_count,
        total_items_count=len(items),
        breaking_precision_match=(expected_breaking == actual_breaking),
        seed_trace_recall=seed_recall,
        caller_trace_recall=caller_recall,
        test_selection_exact=test_exact,
    )
    return items, step0, thinking_text, report
