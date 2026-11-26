# -*- coding: utf-8 -*-
"""Parsers for public release notes, unified git diffs, and sample bundles."""
from __future__ import annotations

import json
import re
from pathlib import Path

from releaseguard.models import DiffFileSummary, ReleaseNoteLine, ReleaseSample

BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.+?)\s*$")
DIFF_FILE_RE = re.compile(r"^\+\+\+\s+b/(.+)$")
HUNK_HEADER_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@.*$")
NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(?:v?\d+\.\d+(?:\.\d+)*(?:[a-zA-Z0-9._-]*)?|\+\d{2}:\d{2}|\d+%|\d+)(?![A-Za-z0-9_])")
CLI_OR_CODE_FLAG_RE = re.compile(r"`([^`]+)`|--[a-zA-Z0-9_-]+|CVE-\d{4}-\d+")


def parse_release_notes(markdown_text: str) -> list[ReleaseNoteLine]:
    """Extract bulleted/numbered release note entries as RN-1..RN-N with line numbers."""
    items: list[ReleaseNoteLine] = []
    idx = 1
    for line_no, raw_line in enumerate(markdown_text.splitlines(), start=1):
        m = BULLET_RE.match(raw_line)
        if m:
            items.append(
                ReleaseNoteLine(
                    line_id=f"RN-{idx}",
                    line_num=line_no,
                    text=m.group(1).strip(),
                )
            )
            idx += 1
    return items


def parse_unified_diff(diff_text: str) -> list[DiffFileSummary]:
    """Parse unified git diff into per-file summaries of hunks, added lines, and removed lines."""
    summaries: list[DiffFileSummary] = []
    cur_file: str | None = None
    hunks: list[str] = []
    added: list[str] = []
    removed: list[str] = []

    def flush() -> None:
        if cur_file is not None:
            summaries.append(
                DiffFileSummary(
                    file_path=cur_file,
                    hunk_headers=list(hunks),
                    added_lines=list(added),
                    removed_lines=list(removed),
                )
            )

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            cur_file = None
            hunks, added, removed = [], [], []
            continue
        m_file = DIFF_FILE_RE.match(line)
        if m_file:
            cur_file = m_file.group(1).strip()
            continue
        if HUNK_HEADER_RE.match(line):
            hunks.append(line.strip())
            continue
        if cur_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])

    flush()
    return summaries


def extract_numeric_and_version_tokens(text: str) -> set[str]:
    """Extract version strings, percentages, time offsets, and standalone numbers."""
    return {m.group(0) for m in NUMBER_TOKEN_RE.finditer(text)}


def extract_code_and_flag_tokens(text: str) -> set[str]:
    """Extract inline code spans, --cli-flags, and CVE identifiers."""
    tokens: set[str] = set()
    for m in CLI_OR_CODE_FLAG_RE.finditer(text):
        tokens.add(m.group(1) if m.group(1) is not None else m.group(0))
    return tokens


def load_sample(sample_dir: Path) -> ReleaseSample:
    """Load a single curated sample folder (`release_notes.md`, `patch.diff`, `ground_truth.json`, `repo/`)."""
    rn_path = sample_dir / "release_notes.md"
    diff_path = sample_dir / "patch.diff"
    gt_path = sample_dir / "ground_truth.json"
    repo_dir = sample_dir / "repo"

    rn_raw = rn_path.read_text(encoding="utf-8")
    diff_raw = diff_path.read_text(encoding="utf-8")
    gt = json.loads(gt_path.read_text(encoding="utf-8"))

    return ReleaseSample(
        sample_id=gt["sample_id"],
        project=gt["project"],
        from_version=gt["from_version"],
        to_version=gt["to_version"],
        release_url=gt["release_url"],
        license=gt["license"],
        release_notes_raw=rn_raw,
        release_lines=parse_release_notes(rn_raw),
        patch_diff_raw=diff_raw,
        diff_files=parse_unified_diff(diff_raw),
        repo_dir=repo_dir,
        ground_truth=gt,
    )


def load_all_samples(samples_root: Path) -> list[ReleaseSample]:
    """Load all sample directories sorted by sample ID."""
    dirs = sorted([p for p in samples_root.iterdir() if p.is_dir() and (p / "ground_truth.json").exists()])
    return [load_sample(d) for d in dirs]
