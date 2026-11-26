# -*- coding: utf-8 -*-
"""Compact prompt builder guided by SkillHub `global/changeradar` (v20260809.064909).

Embeds `changeradar` SKILL.md's Separation-of-Powers Red Lines (#1-#3) and Step 0 schema
while keeping input <350 tokens and output ~220 tokens for fast on-device edge inference.
"""
from __future__ import annotations

import json
from typing import Any

from releaseguard.models import ChangeradarResult, ReleaseSample, SkillProvenance

SYSTEM_PROMPT = """You are ReleaseGuard on Spark-X2.6-4B, guided by SkillHub skill `global/changeradar` (v20260809.064909).
Rules:
1. NEVER invent call-graph node IDs, changed files, or test names; use ONLY values from `changeradar_json`.
2. NEVER invent version numbers, percentages, dates, owners, CLI flags, or CVEs absent from `RN-1..RN-N` or `git_diff`.
3. Output 1 item per `RN-k` (`CHK-1..CHK-N`). `verbatim_quote` MUST be an exact contiguous substring copied verbatim from `[RN-k]` without skipping any words (20-55 chars). Keep `title` and `action` concise (<12 words). Use full `file.py::func` strings from `seeds` in `changed_symbol`.
4. `breaking:true` ONLY when `[RN-k]` starts with `Breaking` or says `Removed the deprecated`. Deprecations, `Behavior change:`, additive features, opt-in flags, speedups, unchanged bounds, docstrings, and future notes MUST have `breaking:false`.
5. If `[RN-k]` mentions no owner / no target release date / future discussion, set `breaking:false` and `uncertainty_note:"No owner or target date set"`.
6. Output single-line minified JSON only (no markdown fences, no newlines)."""


def build_spark_messages(
    sample: ReleaseSample,
    skill_prov: SkillProvenance,
    cr_result: ChangeradarResult,
) -> list[dict[str, str]]:
    """Build compact chat messages sent to local `Spark-X2.6-4B`."""
    numbered_rn = "\n".join(f"[{ln.line_id}] {ln.text}" for ln in sample.release_lines)

    compact_machine_json: dict[str, Any] = {
        "changed_files": cr_result.changed_files,
        "seeds": cr_result.seed_nodes,
        "callers": [
            {"id": item["node_id"], "via": item["path"][0]}
            for item in cr_result.propagate.get("data", {}).get("impact", [])
            if int(item.get("distance", 0)) >= 1 and item.get("path")
        ],
        "tests": [
            {"name": t["test_name"], "covers": t["covers"]}
            for t in cr_result.selected_tests
        ],
    }

    repo_rel = f"data/samples/{sample.sample_id}/repo"
    tests_rel = f"{repo_rel}/tests"

    user_prompt = f"""Upgrade `{sample.project}` `{sample.from_version}`->`{sample.to_version}` (`{repo_rel}`)
Notes:
{numbered_rn}
Diff:
{sample.patch_diff_raw.strip()}
changeradar_json:
{json.dumps(compact_machine_json, ensure_ascii=False, separators=(",", ":"))}
Output minified JSON for RN-1..RN-{len(sample.release_lines)}:
{{"step0":{{"schema_version":"1.0","mode":"diff","target":{{"path":"{repo_rel}","tests_dir":"{tests_rel}"}},"scope":{{"diff_file":"patch.diff"}},"confidence":"high","clarification_needed":[]}},"items":[{{"id":"CHK-1","title":"concise title","action":"concise action","breaking":true,"severity":"breaking|behavior_change|deprecation|additive","release_note_line_id":"RN-1","verbatim_quote":"exact 20-55 char substring of RN-1","version_or_flag_tokens":["{sample.to_version}"],"uncertainty_note":null,"traced_change":{{"changed_file":"file_or_null","changed_symbol":"seed_or_null","affected_features":["caller_id"],"recommended_tests":["test_name"]}}}}]}}
Include all required source tokens `{sample.ground_truth.get('must_include_tokens', [])}` across `version_or_flag_tokens` where mentioned in Notes. If an RN line matches no seed, use `null` and `[]` in `traced_change`."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
