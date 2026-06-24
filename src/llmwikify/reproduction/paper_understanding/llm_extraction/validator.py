"""Validate extraction outputs + generate human-readable preview.md.

Validates JSON structure of plan.json, track_a.json, track_b_pass1.json,
track_b_pass2.json. Generates quant/papers/{id}/preview.md summarizing
the extraction for human review.

Does NOT call LLM. Pure structural validation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Issue levels ────────────────────────────────────────────


@dataclass
class ValidationIssue:
    """A single validation finding."""
    level: str          # "error" | "warning" | "info"
    file: str           # which output file
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── Per-file validators ─────────────────────────────────────


def _validate_plan(plan_data: dict) -> list[ValidationIssue]:
    issues = []
    if not plan_data.get("paper_id"):
        issues.append(ValidationIssue("error", "plan.json", "missing paper_id"))
    if not plan_data.get("source_path"):
        issues.append(ValidationIssue("warning", "plan.json", "missing source_path"))
    p2 = plan_data.get("stage1_call2_plan", {})
    if not p2.get("success"):
        issues.append(ValidationIssue("error", "plan.json", "stage1_call2 failed"))
    if p2.get("confidence", 0) < 0.6:
        issues.append(ValidationIssue(
            "warning", "plan.json",
            f"low planner confidence: {p2.get('confidence')}",
        ))
    if not p2.get("schema_choice"):
        issues.append(ValidationIssue("error", "plan.json", "missing schema_choice"))
    if p2.get("schema_choice") not in {"factor", "signal", "allocation", "summary"}:
        issues.append(ValidationIssue("error", "plan.json", f"invalid schema_choice: {p2.get('schema_choice')}"))
    return issues


def _validate_track_a(track_a_data: dict) -> list[ValidationIssue]:
    issues = []
    if not track_a_data.get("success"):
        issues.append(ValidationIssue(
            "error", "track_a.json",
            f"track_a failed: {track_a_data.get('error')}",
        ))
        return issues
    schema = track_a_data.get("schema_choice")
    if schema not in {"factor", "signal", "allocation", "summary"}:
        issues.append(ValidationIssue("error", "track_a.json", f"invalid schema: {schema}"))
    tier1 = track_a_data.get("tier1", {})
    if not tier1:
        issues.append(ValidationIssue("error", "track_a.json", "tier1 is empty"))
    elif isinstance(tier1, dict):
        meta = tier1.get("paper_metadata", {})
        if not meta.get("title"):
            issues.append(ValidationIssue("warning", "track_a.json", "tier1.paper_metadata.title missing"))
        if not meta.get("authors"):
            issues.append(ValidationIssue("info", "track_a.json", "tier1.paper_metadata.authors missing"))
    return issues


def _validate_track_b_pass1(pass1_data: dict) -> list[ValidationIssue]:
    issues = []
    enabled = pass1_data.get("enabled", True)
    if not enabled:
        return issues  # skipped summary is not a problem
    n = pass1_data.get("n_pass1", 0)
    if n == 0:
        issues.append(ValidationIssue(
            "error", "track_b_pass1.json",
            f"no signals extracted: {pass1_data.get('error')}",
        ))
        return issues
    sigs = pass1_data.get("pass1_signals", [])
    if not isinstance(sigs, list):
        issues.append(ValidationIssue("error", "track_b_pass1.json", "pass1_signals not a list"))
        return issues
    for i, s in enumerate(sigs):
        if not s.get("name"):
            issues.append(ValidationIssue(
                "warning", "track_b_pass1.json",
                f"signal #{i+1} has empty name",
            ))
        if not s.get("formula_brief"):
            issues.append(ValidationIssue(
                "warning", "track_b_pass1.json",
                f"signal '{s.get('name')}' has empty formula",
            ))
    n_calls = pass1_data.get("llm_calls", 1)
    if n > 0 and n_calls > 1 and n < 5:
        # batching triggered but got very few signals
        issues.append(ValidationIssue(
            "info", "track_b_pass1.json",
            f"batched ({n_calls} calls) but only {n} signals",
        ))
    return issues


def _validate_track_b_pass2(pass2_data: dict) -> list[ValidationIssue]:
    issues = []
    n_complete = pass2_data.get("n_pass2_complete", 0)
    n_failed = pass2_data.get("n_pass2_failed", 0)
    n_pass1 = pass2_data.get("n_pass1", 0)
    details = pass2_data.get("pass2_details", [])
    if n_pass1 > 0 and n_complete == 0 and n_failed > 0:
        issues.append(ValidationIssue(
            "error", "track_b_pass2.json",
            f"all {n_pass1} pass2 calls failed",
        ))
    for i, d in enumerate(details):
        if not d.get("success"):
            issues.append(ValidationIssue(
                "warning", "track_b_pass2.json",
                f"factor {i+1} ({d.get('name','?')}) failed: {d.get('error')}",
            ))
            continue
        l1 = d.get("l1", {})
        if not l1 or not l1.get("formula"):
            issues.append(ValidationIssue(
                "warning", "track_b_pass2.json",
                f"factor '{d.get('name')}' L1 missing formula",
            ))
    return issues


# ── Main entry point ────────────────────────────────────────


@dataclass
class ValidationReport:
    paper_id: str
    issues: list[ValidationIssue] = field(default_factory=list)
    files_checked: list[str] = field(default_factory=list)
    files_missing: list[str] = field(default_factory=list)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    def by_level(self, level: str) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == level]

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "issues": [i.to_dict() for i in self.issues],
            "files_checked": self.files_checked,
            "files_missing": self.files_missing,
            "n_errors": self.n_errors,
            "n_warnings": self.n_warnings,
        }


def validate_paper_outputs(work_dir: Path) -> ValidationReport:
    """Validate all extraction outputs in a paper's work dir."""
    work_dir = Path(work_dir)
    report = ValidationReport(paper_id=work_dir.name)

    plan_path = work_dir / "plan.json"
    if plan_path.exists():
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            report.issues.extend(_validate_plan(data))
            report.files_checked.append("plan.json")
        except json.JSONDecodeError as e:
            report.issues.append(ValidationIssue("error", "plan.json", f"invalid JSON: {e}"))
    else:
        report.files_missing.append("plan.json")

    for fname, validator in [
        ("track_a.json", _validate_track_a),
        ("track_b_pass1.json", _validate_track_b_pass1),
    ]:
        path = work_dir / fname
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                report.issues.extend(validator(data))
                report.files_checked.append(fname)
            except json.JSONDecodeError as e:
                report.issues.append(ValidationIssue("error", fname, f"invalid JSON: {e}"))
        else:
            report.files_missing.append(fname)

    # Pass 2: try combined file, then fall back to per-factor partials
    pass2_path = work_dir / "track_b_pass2.json"
    pass2_data: dict | None = None
    if pass2_path.exists():
        try:
            pass2_data = json.loads(pass2_path.read_text(encoding="utf-8"))
            report.files_checked.append("track_b_pass2.json")
        except json.JSONDecodeError as e:
            report.issues.append(ValidationIssue("error", "track_b_pass2.json", f"invalid JSON: {e}"))
    else:
        partials = sorted(work_dir.glob("track_b_pass2_*.json"))
        if partials:
            all_details = []
            for p in partials:
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and d.get("name"):
                        all_details.append(d)
                except json.JSONDecodeError as e:
                    report.issues.append(ValidationIssue("error", p.name, f"invalid JSON: {e}"))
            if all_details:
                pass2_data = {
                    "n_pass1": len(all_details),
                    "n_pass2_complete": sum(1 for d in all_details if d.get("success")),
                    "n_pass2_failed": sum(1 for d in all_details if not d.get("success")),
                    "pass2_details": all_details,
                }
                report.files_checked.extend(p.name for p in partials)

    if pass2_data is not None:
        report.issues.extend(_validate_track_b_pass2(pass2_data))
    else:
        report.files_missing.append("track_b_pass2.json")

    return report
