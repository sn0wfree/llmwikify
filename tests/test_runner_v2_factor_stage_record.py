"""Tests for FactorStage record path (P0 refactor).

Covers:
  - _record_one: calls _update_state / log_row / _persist_result / _log_outcome in order
  - _run_one_with_recording: serial path (no lock)
  - _run_one_safe: parallel path (lock around _record_one)
  - _handle_parallel_failure: synthetic result uses _fail_result (Bug 5)
  - _load_skipped_results: handles corrupt JSON gracefully (Bug 6)

Note: FactorStage/FactorRunner use __slots__, so mock patches are applied
at the CLASS level (patch.object(FactorStage, ...)) not at the instance level.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_101_alphas_v2 import (
    FactorReporter,
    FactorStage,
    RunConfig,
)

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def track_b_path(tmp_path: Path) -> Path:
    cp = tmp_path / "track_b_checkpoint.json"
    cp.write_text(
        json.dumps({"pass1_signals": [{"index": 1, "formula_brief": "x"}]}),
        encoding="utf-8",
    )
    return cp


@pytest.fixture
def stage(track_b_path: Path, tmp_path: Path) -> FactorStage:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = RunConfig(
        track_b_path=track_b_path,
        output_dir=output_dir,
        factors_dir=tmp_path / "factors",
        alpha_start=1,
        alpha_end=3,
        no_delay=True,
    )
    return FactorStage(config)


# ─── _record_one ─────────────────────────────────────────────────────


class TestRecordOne:
    def test_calls_all_four_steps(self, stage: FactorStage) -> None:
        """_record_one must call update_state → log_row → persist_result → log_outcome in order."""
        result = {"status": "success", "alpha_index": 1, "elapsed_sec": 1.5,
                  "ic_mean": 0.02, "icir": 0.1, "ic_winrate": 0.5}
        call_order: list[str] = []

        # Note: class-level mock patches pass args only (no self), because mock
        # acts as a descriptor that handles self binding at call time.
        with patch.object(FactorStage, "_update_state",
                          side_effect=lambda i, r: call_order.append("update_state")):
            with patch.object(FactorReporter, "log_row",
                              side_effect=lambda i, r, t: call_order.append("log_row")):
                with patch.object(FactorStage, "_persist_result",
                                  side_effect=lambda i, r: call_order.append("persist")):
                    with patch.object(FactorStage, "_log_outcome",
                                      side_effect=lambda i, r: call_order.append("log_outcome")):
                        stage._record_one(1, result, 0.0)

        assert call_order == ["update_state", "log_row", "persist", "log_outcome"]

    def test_updates_results_and_failures(self, stage: FactorStage) -> None:
        """_update_state inside _record_one appends result + increments failures."""
        result = {"status": "failed", "stage": "react", "error": "boom",
                  "alpha_index": 1, "code_chars": 0}
        stage._record_one(1, result, 0.0)
        assert len(stage.results) == 1
        assert stage.results[0] is result
        assert stage.failures == 1

    def test_persist_writes_json(self, stage: FactorStage) -> None:
        """_record_one's _persist_result writes single_factor_NNN.json to output_dir."""
        result = {"status": "success", "alpha_index": 1, "ic_mean": 0.02,
                  "icir": 0.1, "ic_winrate": 0.5, "elapsed_sec": 1.0}
        stage._record_one(1, result, 0.0)
        json_path = stage.config.output_dir / "single_factor_001.json"
        assert json_path.exists()
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["status"] == "success"
        assert loaded["alpha_index"] == 1


# ─── _run_one_with_recording (serial path) ──────────────────────────


class TestRunOneWithRecording:
    def test_no_lock_serial(self, stage: FactorStage) -> None:
        """Serial path: no lock, calls run_one_factor + _record_one."""
        fake_result = {"status": "success", "alpha_index": 1, "ic_mean": 0.02,
                       "icir": 0.1, "ic_winrate": 0.5, "elapsed_sec": 1.0}
        with patch.object(FactorStage, "run_one_factor", return_value=fake_result):
            with patch.object(FactorStage, "_record_one") as record:
                stage.batch_t0 = 0.0
                result = stage._run_one_with_recording(1)
                assert record.called
                assert result is fake_result

    def test_appends_to_results(self, stage: FactorStage) -> None:
        """Serial path appends to results after _record_one (mocked)."""
        fake_result = {"status": "success", "alpha_index": 1, "ic_mean": 0.02,
                       "icir": 0.1, "ic_winrate": 0.5, "elapsed_sec": 1.0}
        with patch.object(FactorStage, "run_one_factor", return_value=fake_result):
            with patch.object(FactorStage, "_record_one",
                              side_effect=lambda i, r, t: stage.results.append(r)):
                stage.batch_t0 = 0.0
                stage._run_one_with_recording(1)
                assert len(stage.results) == 1
                assert stage.results[0]["alpha_index"] == 1


# ─── _run_one_safe (parallel path) ──────────────────────────────────


class TestRunOneSafe:
    def test_lock_wraps_record_only(self, stage: FactorStage) -> None:
        """Parallel: lock only wraps _record_one, NOT run_one_factor.

        Bug 3 修复 regression test: ensure the LLM call is OUTSIDE the lock.
        """
        fake_result = {"status": "success", "alpha_index": 1, "elapsed_sec": 1.0}
        call_order: list[str] = []

        # Mock the module-level lock so we can observe acquisition order
        import scripts.run_101_alphas_v2 as v2_mod

        class _TrackingLock:
            def __init__(self, real_lock):
                self._real = real_lock

            def __enter__(self):
                call_order.append("lock_acquired")
                return self._real.__enter__()

            def __exit__(self, *args):
                call_order.append("lock_released")
                return self._real.__exit__(*args)

        with patch.object(FactorStage, "run_one_factor",
                          side_effect=lambda *a, **kw: (
                              call_order.append("run_one_factor"), fake_result
                          )[1]):
            with patch.object(FactorStage, "_record_one",
                              side_effect=lambda i, r, t: call_order.append("record_one")):
                # Patch the lock used inside _run_one_safe
                original_lock = v2_mod._print_lock
                v2_mod._print_lock = _TrackingLock(original_lock)
                try:
                    stage._run_one_safe(1)
                finally:
                    v2_mod._print_lock = original_lock

        # Bug 3 fix: run_one_factor MUST be outside the lock window
        assert call_order.index("run_one_factor") < call_order.index("lock_acquired")
        assert call_order.index("lock_acquired") < call_order.index("record_one")
        assert call_order.index("record_one") < call_order.index("lock_released")


# ─── _handle_parallel_failure ────────────────────────────────────────


class TestHandleParallelFailure:
    def test_appends_synthetic_with_full_fields(self, stage: FactorStage) -> None:
        """Bug 5: synthetic result must have all required fields (code_chars=0)."""
        stage._handle_parallel_failure(42, "TimeoutError", "future boom")
        assert len(stage.results) == 1
        r = stage.results[0]
        assert r["status"] == "failed"
        assert r["alpha_index"] == 42
        assert r["stage"] == "TimeoutError"
        assert r["error"] == "future boom"
        assert r["code"] is None
        assert r["code_chars"] == 0  # ← Bug 5 fix
        assert r["ic_mean"] is None
        assert r["icir"] is None
        assert r["ic_winrate"] is None
        assert "elapsed_sec" in r

    def test_increments_failures(self, stage: FactorStage) -> None:
        stage._handle_parallel_failure(1, "Exception", "boom")
        stage._handle_parallel_failure(2, "Exception", "boom")
        stage._handle_parallel_failure(3, "Exception", "boom")
        assert stage.failures == 3
        assert len(stage.results) == 3


# ─── _load_skipped_results (Bug 6) ──────────────────────────────────


class TestLoadSkippedResults:
    def test_skips_corrupt_json(self, stage: FactorStage, caplog) -> None:
        """Bug 6: corrupt JSON in single_factor_NNN.json should be skipped, not crash."""
        (stage.config.output_dir / "single_factor_001.json").write_text(
            json.dumps({"status": "success", "alpha_index": 1, "ic_mean": 0.01}),
            encoding="utf-8",
        )
        (stage.config.output_dir / "single_factor_002.json").write_text(
            "not valid json {{{",
            encoding="utf-8",
        )

        caplog.set_level(logging.WARNING, logger="run_101_alphas_v2")
        stage._load_skipped_results({1, 2})
        # Only valid result appended
        assert len(stage.results) == 1
        assert stage.results[0]["alpha_index"] == 1
        # Warning logged for corrupt one
        assert any("002" in r.message or "skip-corrupt" in r.message for r in caplog.records)

    def test_appends_missing_alpha_index(self, stage: FactorStage) -> None:
        """If alpha_index not in loaded JSON, fill it from idx."""
        (stage.config.output_dir / "single_factor_001.json").write_text(
            json.dumps({"status": "success", "ic_mean": 0.01}),
            encoding="utf-8",
        )
        stage._load_skipped_results({1})
        assert stage.results[0]["alpha_index"] == 1
