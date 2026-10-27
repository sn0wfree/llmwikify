#!/usr/bin/env python3
"""Validate llmwikify multi-agent refactor handoff artifacts.

The refactor pipeline (see ``docs/designs/refactor-multi-agent-protocol.md``)
moves work between agents through JSON artifacts. Each stage writes one
artifact; the next stage must not start until the artifact passes the gate
enforced here.

    Recon ──▶ Design ──▶ Implement ──▶ Review ──▶ merge
                                                  └──▶ Bench ──▶ merge

Audit runs per batch, not per task, and gates nothing.

File naming: ``<task_id>.<stage>.json``
e.g.         ``u1-llm-dispatch.design.json``

Usage:

    python scripts/validate_handoff.py docs/designs/refactor-handoff
    python scripts/validate_handoff.py handoff/u1-llm-dispatch.review.json
    python scripts/validate_handoff.py docs/designs/refactor-handoff --json

Exit codes: 0 = every artifact passed, 1 = at least one artifact failed or
was blocked by a gate, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pipeline stages, in the order a task flows through them.
STAGES: tuple[str, ...] = (
    "recon",
    "design",
    "implement",
    "review",
    "bench",
    "audit",
)

# Fields every artifact of a given stage must carry.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "recon": ("scope", "candidates"),
    "design": ("task_id", "decision", "boundary"),
    "implement": ("task_id", "status", "files_changed"),
    "review": ("task_id", "verdict"),
    "bench": ("task_id", "before", "after", "regression"),
    "audit": ("batch",),
}

# Which field of which stage is constrained to a fixed value set.
ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "design": ("decision",),
    "implement": ("status",),
    "review": ("verdict",),
}

ALLOWED_VALUES: dict[str, tuple[str, ...]] = {
    "decision": ("proceed", "observe", "reject"),
    "status": ("done", "blocked"),
    "verdict": ("approve", "request_changes", "reject"),
}


@dataclass(frozen=True)
class HandoffResult:
    """Outcome of validating one handoff artifact."""

    path: Path
    stage: str
    ok: bool
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "stage": self.stage,
            "ok": self.ok,
            "errors": list(self.errors),
        }


def infer_stage(path: Path) -> str | None:
    """Infer the pipeline stage from a ``<task_id>.<stage>.json`` filename.

    Returns None when the name does not carry a known stage suffix.
    """
    name = path.name
    if not name.endswith(".json"):
        return None
    stem = name[: -len(".json")]
    if "." not in stem:
        return None
    candidate = stem.rsplit(".", 1)[1]
    return candidate if candidate in STAGES else None


def gate_errors(stage: str, data: dict[str, Any]) -> list[str]:
    """Return why this artifact must not advance the pipeline.

    The gate is the point of the whole mechanism: a Reviewer verdict of
    ``request_changes`` or a Benchmarker that found a regression blocks
    the merge no matter how good the rest of the artifact looks.
    """
    if stage == "recon":
        if not data.get("candidates"):
            return ["candidates is empty — nothing to design"]
        return []
    if stage == "design":
        decision = data.get("decision")
        if decision != "proceed":
            return [f"decision is {decision!r}, not 'proceed' — handoff blocked"]
        return []
    if stage == "implement":
        status = data.get("status")
        if status != "done":
            return [f"status is {status!r}, not 'done' — handoff blocked"]
        return []
    if stage == "review":
        verdict = data.get("verdict")
        if verdict != "approve":
            return [f"verdict is {verdict!r}, not 'approve' — handoff blocked"]
        return []
    if stage == "bench":
        regression = data.get("regression")
        if regression is not False:
            return ["regression is not False — handoff blocked"]
        return []
    return []


def validate_document(stage: str, data: Any) -> list[str]:
    """Validate one parsed handoff document; returns a list of errors.

    An empty list means the artifact is valid *and* passes its gate.
    """
    if stage not in REQUIRED_FIELDS:
        return [f"unknown stage {stage!r} (expected one of {', '.join(STAGES)})"]
    if not isinstance(data, dict):
        return ["document root must be a JSON object"]

    missing = [key for key in REQUIRED_FIELDS[stage] if key not in data]
    if missing:
        # Do not run the gate on an incomplete document — the missing field
        # is the real problem, and the gate would only restate it.
        return [f"missing required field {key!r}" for key in missing]

    errors: list[str] = []
    for key in ENUM_FIELDS.get(stage, ()):
        value = data[key]
        allowed = ALLOWED_VALUES[key]
        if value not in allowed:
            errors.append(f"{key}={value!r} is not one of {allowed}")

    if stage == "bench" and not isinstance(data["regression"], bool):
        errors.append(
            f"regression must be a JSON boolean, got {type(data['regression']).__name__}"
        )

    errors.extend(gate_errors(stage, data))
    return errors


def validate_file(path: Path, stage: str | None = None) -> HandoffResult:
    """Read and validate one handoff artifact from disk."""
    resolved = stage or infer_stage(path)
    if resolved is None:
        return HandoffResult(
            path,
            "?",
            False,
            ("cannot infer stage from filename; expected <task_id>.<stage>.json",),
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return HandoffResult(path, resolved, False, (f"cannot read file: {exc}",))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return HandoffResult(path, resolved, False, (f"invalid JSON: {exc}",))
    errors = validate_document(resolved, data)
    return HandoffResult(path, resolved, not errors, tuple(errors))


def _collect(paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Split the CLI paths into handoff artifacts and non-artifact files."""
    files: list[Path] = []
    skipped: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        if candidate.is_dir():
            for found in sorted(candidate.rglob("*.json")):
                if infer_stage(found) is None:
                    skipped.append(found)
                else:
                    files.append(found)
        else:
            files.append(candidate)
    return files, skipped


def main(argv: list[str] | None = None) -> int:
    # The report uses emoji (✅/❌). On a Windows console with a legacy code
    # page (GBK) — or any time stdout is a pipe rather than a real console
    # handle — the default stream encoding cannot represent them, and the
    # script dies with UnicodeEncodeError *after* validation already
    # succeeded. Same guard as scripts/check_architecture.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Stream has no reconfigure (e.g. replaced by a test capture)
            # or is already closed — nothing to do.
            pass

    parser = argparse.ArgumentParser(
        prog="validate_handoff",
        description="Validate llmwikify refactor handoff artifacts and their gates.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="handoff file(s) or directory(ies) to validate",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        help="force the stage instead of inferring it from the filename",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a machine-readable report instead of text",
    )
    args = parser.parse_args(argv)

    files, skipped = _collect(args.paths)
    missing = [p for p in files if not p.is_file()]
    if missing:
        for path in missing:
            print(f"❌ path not found: {path}", file=sys.stderr)
        return 2
    if not files:
        print("❌ no handoff JSON files found", file=sys.stderr)
        return 2

    results = [validate_file(path, args.stage) for path in files]
    failed = [result for result in results if not result.ok]

    if args.as_json:
        payload = {
            "total": len(results),
            "failed": len(failed),
            "skipped": [str(path) for path in skipped],
            "results": [result.as_dict() for result in results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if failed else 0

    for result in results:
        if result.ok:
            print(f"✅ {result.path}  [{result.stage}]")
        else:
            print(f"❌ {result.path}  [{result.stage}]")
            for error in result.errors:
                print(f"     - {error}")
    if skipped:
        print(f"\n⚠️ skipped {len(skipped)} file(s) not named <task_id>.<stage>.json")
    print()
    if failed:
        print(
            f"❌ {len(failed)}/{len(results)} handoff artifact(s) failed — pipeline blocked"
        )
        return 1
    print(f"✅ {len(results)}/{len(results)} handoff artifact(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
