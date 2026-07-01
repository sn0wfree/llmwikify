"""Tests for RecordStage (PR9c).

Covers:
  - record(): calls _update_state → log_row → _persist_one → _log_outcome in order
  - _update_state: appends to results, increments failures on fail
  - _persist_one: writes JSON via sink, tolerates exceptions
  - _idx_from_result: extracts alpha_index from metadata
  - _log_outcome: logs success vs failure with right text
  - integration: 4-step workflow with real SingleJsonSink
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from llmwikify.reproduction.backtest.base import FactorResult
from llmwikify.reproduction.factor import RecordStage
from llmwikify.reproduction.reporting.reporter import BatchReporter
from llmwikify.reproduction.signal_source.base import Signal
from llmwikify.reproduction.sink.single_json import SingleJsonSink

# ─── Fixtures ────────────────────────────────────────────────────────


def _make_fr(idx: int, status: str = "success", **kwargs) -> FactorResult:
    return FactorResult(
        signal=Signal(
            id=f"{idx:03d}",
            name=f"alpha-{idx:03d}",
            formula_brief="f(x) = x",
            metadata={"alpha_index": idx, "index": idx},
        ),
        status=status,
        backtest={"ic_mean": kwargs.get("ic_mean", 0.02),
                  "icir": kwargs.get("icir", 0.1),
                  "win_rate": kwargs.get("ic_winrate", 0.5)},
        elapsed_sec=kwargs.get("elapsed_sec", 1.0),
        stage=kwargs.get("stage"),
        error=kwargs.get("error"),
        code=kwargs.get("code"),
        code_chars=kwargs.get("code_chars", 0),
    )


@pytest.fixture
def results() -> list:
    return []


@pytest.fixture
def failures() -> list:
    return [0]


@pytest.fixture
def sink(tmp_path: Path) -> SingleJsonSink:
    return SingleJsonSink(output_dir=tmp_path / "output")


@pytest.fixture
def stage(sink: SingleJsonSink, results: list, failures: list) -> RecordStage:
    return RecordStage(single_sink=sink, results=results, failures=failures)


# ─── record() — call order ───────────────────────────────────────────


class TestRecordOrder:
    def test_calls_all_four_steps(self, stage: RecordStage) -> None:
        """record() must call update_state → log_row → persist → log_outcome in order."""
        result = _make_fr(1, status="success", elapsed_sec=1.5)
        call_order: list[str] = []

        with patch.object(RecordStage, "_update_state",
                          side_effect=lambda r: call_order.append("update_state")):
            with patch.object(BatchReporter, "log_row",
                              side_effect=lambda i, r, t: call_order.append("log_row")):
                with patch.object(RecordStage, "_persist_one",
                                  side_effect=lambda r: call_order.append("persist")):
                    with patch.object(RecordStage, "_log_outcome",
                                      side_effect=lambda i, r: call_order.append("log_outcome")):
                        stage.record(result, 0.0)

        assert call_order == ["update_state", "log_row", "persist", "log_outcome"]


# ─── _update_state ───────────────────────────────────────────────────


class TestUpdateState:
    def test_appends_to_results(self, stage: RecordStage, results: list) -> None:
        result = _make_fr(1, status="success")
        stage._update_state(result)
        assert results == [result]

    def test_increments_failures_on_fail(self, stage: RecordStage, failures: list) -> None:
        result = _make_fr(1, status="failed", stage="react", error="boom")
        stage._update_state(result)
        assert failures[0] == 1

    def test_no_increment_on_success(self, stage: RecordStage, failures: list) -> None:
        result = _make_fr(1, status="success")
        stage._update_state(result)
        assert failures[0] == 0

    def test_multiple_results_accumulate(self, stage: RecordStage, results: list, failures: list) -> None:
        for i, status in [(1, "success"), (2, "failed"), (3, "success"), (4, "failed")]:
            stage._update_state(_make_fr(i, status=status))
        assert len(results) == 4
        assert failures[0] == 2


# ─── _persist_one ────────────────────────────────────────────────────


class TestPersistOne:
    def test_writes_json(self, stage: RecordStage, sink: SingleJsonSink, tmp_path: Path) -> None:
        result = _make_fr(1, status="success", ic_mean=0.02, icir=0.1, ic_winrate=0.5)
        stage._persist_one(result)
        # SingleJsonSink writes to sink.output_dir
        json_path = sink.output_dir / "single_factor_001.json"
        assert json_path.exists()
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["status"] == "success"
        assert loaded["alpha_index"] == 1

    def test_tolerates_sink_exception(self, sink: SingleJsonSink, results: list, failures: list, caplog) -> None:
        """Bug: a single sink error must not abort the batch.

        RecordStage uses __slots__, so we test by replacing `single_sink`
        with a raising stub (instance attribute assignment is allowed
        even with __slots__).
        """
        class _RaisingSink:
            def write_one(self, result: Any) -> Path:
                raise OSError("disk full")

        stage = RecordStage(
            single_sink=_RaisingSink(),  # type: ignore[arg-type]
            results=results,
            failures=failures,
        )
        result = _make_fr(1)
        caplog.set_level(logging.WARNING, logger="llmwikify.reproduction.factor.record_stage")
        # Should NOT raise
        stage._persist_one(result)
        assert any("disk full" in r.message for r in caplog.records)


# ─── _idx_from_result ────────────────────────────────────────────────


class TestIdxFromResult:
    def test_extracts_alpha_index(self, stage: RecordStage) -> None:
        r = _make_fr(42)
        assert stage._idx_from_result(r) == 42

    def test_falls_back_to_index(self, stage: RecordStage) -> None:
        r = FactorResult(
            signal=Signal(
                id="001",
                name="x",
                formula_brief="",
                metadata={"index": 7},  # only 'index', no 'alpha_index'
            ),
            status="success",
            backtest={},
            elapsed_sec=0.0,
        )
        assert stage._idx_from_result(r) == 7

    def test_returns_zero_when_no_metadata(self, stage: RecordStage) -> None:
        r = FactorResult(
            signal=Signal(id="001", name="x", formula_brief="", metadata={}),
            status="success",
            backtest={},
            elapsed_sec=0.0,
        )
        assert stage._idx_from_result(r) == 0

    def test_ignores_non_int_values(self, stage: RecordStage) -> None:
        r = FactorResult(
            signal=Signal(
                id="001", name="x", formula_brief="",
                metadata={"alpha_index": "not an int", "index": 9},
            ),
            status="success",
            backtest={},
            elapsed_sec=0.0,
        )
        assert stage._idx_from_result(r) == 9


# ─── _log_outcome ────────────────────────────────────────────────────


class TestLogOutcome:
    def test_success_logs_info(self, stage: RecordStage, caplog) -> None:
        caplog.set_level(logging.INFO, logger="llmwikify.reproduction.factor.record_stage")
        stage._log_outcome(1, {"status": "success", "elapsed_sec": 1.5})
        # Format: "alpha-001: success (1.5s)"
        assert any("success" in r.message and "1.5" in r.message for r in caplog.records)

    def test_failure_logs_warning(self, stage: RecordStage, caplog) -> None:
        caplog.set_level(logging.WARNING, logger="llmwikify.reproduction.factor.record_stage")
        stage._log_outcome(2, {"status": "failed", "error": "LLM timeout"})
        assert any("failed" in r.message and "LLM timeout" in r.message for r in caplog.records)

    def test_failure_truncates_long_error(self, stage: RecordStage, caplog) -> None:
        caplog.set_level(logging.WARNING, logger="llmwikify.reproduction.factor.record_stage")
        long_error = "x" * 200
        stage._log_outcome(1, {"status": "failed", "error": long_error})
        # Truncated to 80 chars
        msg = next(r.message for r in caplog.records if "failed" in r.message)
        assert len(msg) < 200  # definitely less than 200

    def test_failure_with_no_error(self, stage: RecordStage, caplog) -> None:
        """No error key → use '?' placeholder."""
        caplog.set_level(logging.WARNING, logger="llmwikify.reproduction.factor.record_stage")
        stage._log_outcome(1, {"status": "failed"})
        assert any("?" in r.message for r in caplog.records)


# ─── Integration ─────────────────────────────────────────────────────


class TestIntegration:
    def test_full_workflow_writes_json(
        self, sink: SingleJsonSink, results: list, failures: list,
    ) -> None:
        stage = RecordStage(single_sink=sink, results=results, failures=failures)
        result = _make_fr(1, status="success", ic_mean=0.02)
        stage.record(result, 0.0)

        # All 4 sub-operations happened
        assert results == [result]
        assert failures[0] == 0  # success → no increment
        json_path = sink.output_dir / "single_factor_001.json"
        assert json_path.exists()
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["status"] == "success"

    def test_failure_increments_count(
        self, sink: SingleJsonSink, results: list, failures: list,
    ) -> None:
        stage = RecordStage(single_sink=sink, results=results, failures=failures)
        for i, status in [(1, "success"), (2, "failed"), (3, "failed")]:
            stage.record(
                _make_fr(i, status=status, error="boom" if status == "failed" else None),
                0.0,
            )
        assert len(results) == 3
        assert failures[0] == 2
