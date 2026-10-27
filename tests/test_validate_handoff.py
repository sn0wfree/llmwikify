"""Tests for scripts/validate_handoff.py.

The validator is the gate of the multi-agent refactor pipeline: a stage
artifact that does not pass must stop the next stage from starting. Two
things therefore need coverage:

1. **Gate semantics** — every "blocked" outcome actually blocks, and no
   valid artifact is rejected by accident.
2. **Robustness** — the CLI must survive a legacy (non-UTF-8) console and
   must not let a malformed document sneak through as "valid".
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "validate_handoff.py"

# One valid artifact per stage, used as the baseline for mutation tests.
VALID: dict[str, dict] = {
    "recon": {"scope": "src/llmwikify/kernel/graph", "candidates": [{"id": "C1"}]},
    "design": {"task_id": "u1", "decision": "proceed", "boundary": "new module"},
    "implement": {"task_id": "u1", "status": "done", "files_changed": ["a.py"]},
    "review": {"task_id": "u1", "verdict": "approve"},
    "bench": {
        "task_id": "u1",
        "before": {"p50_ms": 120},
        "after": {"p50_ms": 45},
        "regression": False,
    },
    "audit": {"batch": "batch-1"},
}


def _load():
    """Import the script as a module (it is not an installed package).

    The module must be registered in ``sys.modules`` *before* execution:
    ``@dataclass`` resolves the class's module through ``sys.modules`` at
    decoration time, so an unregistered module raises AttributeError.
    """
    spec = importlib.util.spec_from_file_location("validate_handoff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_artifact(root: Path, stage: str, payload: dict) -> Path:
    path = root / f"u1-llm-dispatch.{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_cli(mod, argv: list[str], monkeypatch) -> tuple[int, str]:
    """Run main() with stdout/stderr captured.

    ``print()`` resolves ``sys.stdout`` from the *real* ``sys`` module, so
    the capture has to patch that, not the script's ``mod.sys`` binding.
    """
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(sys, "stderr", buf)
    rc = mod.main(argv)
    return rc, buf.getvalue()


# ─── gate semantics ───────────────────────────────────────────────────


@pytest.mark.parametrize("stage", sorted(VALID))
def test_valid_artifact_passes(stage: str) -> None:
    """Every stage's canonical artifact validates with no errors."""
    mod = _load()
    assert mod.validate_document(stage, VALID[stage]) == []


def test_missing_required_field_is_reported_once() -> None:
    """A missing field is the real problem; the gate must not restate it."""
    mod = _load()
    payload = {"task_id": "u1", "status": "done"}
    errors = mod.validate_document("implement", payload)
    assert errors == ["missing required field 'files_changed'"]


@pytest.mark.parametrize("decision", ["observe", "reject"])
def test_design_not_proceed_blocks(decision: str) -> None:
    mod = _load()
    payload = {"task_id": "u1", "decision": decision, "boundary": "x"}
    errors = mod.validate_document("design", payload)
    assert errors and "not 'proceed'" in errors[0]


def test_implement_blocked_blocks() -> None:
    mod = _load()
    payload = {"task_id": "u1", "status": "blocked", "files_changed": []}
    errors = mod.validate_document("implement", payload)
    assert errors and "not 'done'" in errors[0]


@pytest.mark.parametrize("verdict", ["request_changes", "reject"])
def test_review_not_approve_blocks(verdict: str) -> None:
    """A reviewer asking for changes must not be wave-throughed."""
    mod = _load()
    payload = {"task_id": "u1", "verdict": verdict}
    errors = mod.validate_document("review", payload)
    assert errors and "not 'approve'" in errors[0]


def test_bench_regression_true_blocks() -> None:
    mod = _load()
    payload = dict(VALID["bench"], regression=True)
    errors = mod.validate_document("bench", payload)
    assert errors and "regression is not False" in errors[0]


def test_bench_regression_must_be_boolean() -> None:
    """``"regression": "false"`` is a bug waiting to happen — reject it."""
    mod = _load()
    payload = dict(VALID["bench"], regression="false")
    errors = mod.validate_document("bench", payload)
    assert any("must be a JSON boolean" in e for e in errors)
    assert any("regression is not False" in e for e in errors)


def test_recon_with_no_candidates_blocks() -> None:
    mod = _load()
    errors = mod.validate_document("recon", {"scope": "x", "candidates": []})
    assert errors and "candidates is empty" in errors[0]


def test_invalid_enum_value_lists_allowed_values() -> None:
    mod = _load()
    payload = {"task_id": "u1", "decision": "maybe", "boundary": "x"}
    errors = mod.validate_document("design", payload)
    assert any("is not one of" in e and "proceed" in e for e in errors)


def test_unknown_stage_is_rejected() -> None:
    mod = _load()
    errors = mod.validate_document("nonsense", {"a": 1})
    assert errors and "unknown stage" in errors[0]


def test_non_object_root_is_rejected() -> None:
    mod = _load()
    errors = mod.validate_document("design", ["not", "a", "dict"])
    assert errors == ["document root must be a JSON object"]


# ─── file handling ────────────────────────────────────────────────────


def test_infer_stage_from_filename() -> None:
    mod = _load()
    assert mod.infer_stage(Path("u1.design.json")) == "design"
    assert mod.infer_stage(Path("u1-llm-dispatch.bench.json")) == "bench"
    assert mod.infer_stage(Path("u1.design.txt")) is None
    assert mod.infer_stage(Path("u1design.json")) is None
    assert mod.infer_stage(Path("u1.unknown.json")) is None


def test_validate_file_reads_from_disk(tmp_path: Path) -> None:
    mod = _load()
    path = _write_artifact(tmp_path, "review", VALID["review"])
    result = mod.validate_file(path)
    assert result.ok
    assert result.stage == "review"
    assert result.errors == ()


def test_validate_file_reports_invalid_json(tmp_path: Path) -> None:
    mod = _load()
    path = tmp_path / "u1.design.json"
    path.write_text("{not json", encoding="utf-8")
    result = mod.validate_file(path)
    assert not result.ok
    assert "invalid JSON" in result.errors[0]


def test_validate_file_reports_unreadable_file(tmp_path: Path) -> None:
    mod = _load()
    result = mod.validate_file(tmp_path / "nope.design.json")
    assert not result.ok
    assert "cannot read file" in result.errors[0]


def test_validate_file_rejects_unnamed_artifact(tmp_path: Path) -> None:
    mod = _load()
    path = tmp_path / "handoff.json"
    path.write_text("{}", encoding="utf-8")
    result = mod.validate_file(path)
    assert not result.ok
    assert "cannot infer stage" in result.errors[0]


# ─── CLI ──────────────────────────────────────────────────────────────


def test_cli_passes_on_valid_directory(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    for stage in VALID:
        _write_artifact(tmp_path, stage, VALID[stage])
    rc, out = _run_cli(mod, [str(tmp_path)], monkeypatch)
    assert rc == 0, out
    assert "handoff artifact(s) valid" in out


def test_cli_fails_when_one_artifact_is_blocked(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    _write_artifact(tmp_path, "design", VALID["design"])
    _write_artifact(tmp_path, "review", {"task_id": "u1", "verdict": "request_changes"})
    rc, out = _run_cli(mod, [str(tmp_path)], monkeypatch)
    assert rc == 1
    assert "not 'approve'" in out
    assert "pipeline blocked" in out


def test_cli_missing_path_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    rc, out = _run_cli(mod, [str(tmp_path / "nope")], monkeypatch)
    assert rc == 2
    assert "path not found" in out


def test_cli_json_report_is_machine_readable(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    _write_artifact(tmp_path, "design", VALID["design"])
    _write_artifact(tmp_path, "bench", dict(VALID["bench"], regression=True))
    rc, out = _run_cli(mod, [str(tmp_path), "--json"], monkeypatch)
    assert rc == 1
    payload = json.loads(out)
    assert payload["total"] == 2
    assert payload["failed"] == 1
    assert {r["stage"] for r in payload["results"]} == {"design", "bench"}


def test_cli_skips_non_handoff_json(tmp_path: Path, monkeypatch) -> None:
    """A stray JSON in the directory must be reported, not silently used."""
    mod = _load()
    _write_artifact(tmp_path, "design", VALID["design"])
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    rc, out = _run_cli(mod, [str(tmp_path)], monkeypatch)
    assert rc == 0, out
    assert "skipped 1 file(s)" in out


@pytest.mark.parametrize("encoding", ["ascii", "gbk"])
def test_cli_survives_non_utf8_console(tmp_path: Path, encoding: str) -> None:
    """Regression net: emoji output must not kill a legacy console.

    Without the UTF-8 guard the CLI dies with UnicodeEncodeError while
    printing the summary — and the non-zero exit would read as "handoff
    failed" rather than "console could not encode the report".
    """
    try:
        "".encode(encoding)
    except LookupError:  # pragma: no cover - codec not available on this box
        pytest.skip(f"{encoding} codec unavailable")

    _write_artifact(tmp_path, "design", VALID["design"])
    env = {**os.environ, "PYTHONIOENCODING": encoding}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert "UnicodeEncodeError" not in proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
