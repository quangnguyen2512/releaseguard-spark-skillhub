# -*- coding: utf-8 -*-
"""Core dataclasses and JSON-serializable schemas for ReleaseGuard."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReleaseNoteLine:
    line_id: str
    line_num: int
    text: str


@dataclass(frozen=True)
class DiffFileSummary:
    file_path: str
    hunk_headers: list[str]
    added_lines: list[str]
    removed_lines: list[str]


@dataclass
class ReleaseSample:
    sample_id: str
    project: str
    from_version: str
    to_version: str
    release_url: str
    license: str
    release_notes_raw: str
    release_lines: list[ReleaseNoteLine]
    patch_diff_raw: str
    diff_files: list[DiffFileSummary]
    repo_dir: Path
    ground_truth: dict[str, Any]


@dataclass(frozen=True)
class SkillProvenance:
    registry: str
    namespace: str
    slug: str
    version: str
    version_id: int
    fingerprint: str
    skill_md_sha256: str
    detail_url: str
    skill_dir: str
    files_verified: int
    self_checks_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeradarResult:
    cache: dict[str, Any]
    callgraph: dict[str, Any]
    diffparse: dict[str, Any]
    propagate: dict[str, Any]
    testselect: dict[str, Any]
    changed_files: list[str]
    seed_nodes: list[str]
    affected_callers: list[str]
    all_impact_nodes: list[str]
    selected_tests: list[dict[str, Any]]
    total_tests: int
    compression_ratio: float
    impact_coverage: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TracedChange:
    changed_file: str | None = None
    changed_symbol: str | None = None
    affected_features: list[str] = field(default_factory=list)
    recommended_tests: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TracedChange":
        if not isinstance(data, dict):
            return cls()
        return cls(
            changed_file=data.get("changed_file") or None,
            changed_symbol=data.get("changed_symbol") or None,
            affected_features=[str(x) for x in (data.get("affected_features") or []) if x],
            recommended_tests=[str(x) for x in (data.get("recommended_tests") or []) if x],
        )


@dataclass
class ChecklistItem:
    id: str
    title: str
    action: str
    breaking: bool
    severity: str
    release_note_line_id: str
    verbatim_quote: str
    version_or_flag_tokens: list[str] = field(default_factory=list)
    uncertainty_note: str | None = None
    traced_change: TracedChange = field(default_factory=TracedChange)
    review_status: str = "pending"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChecklistItem":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            action=str(data.get("action", "")),
            breaking=bool(data.get("breaking", False)),
            severity=str(data.get("severity", "additive")),
            release_note_line_id=str(data.get("release_note_line_id", "")),
            verbatim_quote=str(data.get("verbatim_quote", "")),
            version_or_flag_tokens=[str(x) for x in (data.get("version_or_flag_tokens") or []) if x is not None],
            uncertainty_note=(str(data["uncertainty_note"]) if data.get("uncertainty_note") else None),
            traced_change=TracedChange.from_dict(data.get("traced_change")),
            review_status=str(data.get("review_status") or "pending"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    gate_id: str
    name: str
    passed: bool
    summary: str
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationReport:
    sample_id: str
    all_gates_passed: bool
    gates: list[GateResult]
    verified_items_count: int
    total_items_count: int
    breaking_precision_match: bool
    seed_trace_recall: float
    caller_trace_recall: float
    test_selection_exact: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
