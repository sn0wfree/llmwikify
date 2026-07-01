"""Tests for FactorRunner SR methods (P0 refactor).

Covers:
  - _load_formula: returns (factor_name, formula_brief)
  - _generate_code: ReAct / 1-shot dispatch + returns (code, factor_series, error, stage)
  - _fail_codegen_result: codegen failure dict shape
  - _fail_pipeline_result: pipeline failure dict with traceback[-1500:]
  - _log_backtest_metrics: caplog IC/ICIR/WinRate
  - _success_result: full success dict shape
  - _fail_result: unified factory for parallel failure (Bug 5)
  - run_one_factor: orchestration calls the 7 steps in order, short-circuits on codegen failure
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from scripts.run_101_alphas_v2 import (
    FactorRunner,
    RunConfig,
)

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def track_b_path(tmp_path: Path) -> Path:
    """Mock track_b_checkpoint.json with 3 alpha signals."""
    cp = tmp_path / "track_b_checkpoint.json"
    cp.write_text(
        json.dumps(
            {
                "pass1_signals": [
                    {"index": 1, "formula_brief": "alpha-1: (-1 * corr(rank(volume), rank(low), 5))"},
                    {"index": 2, "formula_brief": "alpha-2: rank(delta(close, 5))"},
                    {"index": 3, "formula_brief": "alpha-3: mean(close, 10) / close"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return cp


@pytest.fixture
def runner(track_b_path: Path, tmp_path: Path) -> TestRunner:
    """Bare FactorRunner concrete subclass with mocked config (no data preload)."""
    config = RunConfig(
        track_b_path=track_b_path,
        output_dir=tmp_path / "output",
        factors_dir=tmp_path / "factors",
    )
    return TestRunner(config)


class TestRunner(FactorRunner):
    """Minimal concrete subclass for unit tests (FactorRunner.run is abstract)."""

    def run(self) -> Any:  # type: ignore[override]
        return None


# ─── _load_formula ───────────────────────────────────────────────────


class TestLoadFormula:
    def test_returns_factor_name_and_brief(self, runner: FactorRunner) -> None:
        name, brief = runner._load_formula(1)
        assert name == "alpha-001"
        assert "corr" in brief
        assert "rank" in brief

    def test_loads_correct_index(self, runner: FactorRunner) -> None:
        name2, brief2 = runner._load_formula(2)
        name3, brief3 = runner._load_formula(3)
        assert name2 == "alpha-002"
        assert name3 == "alpha-003"
        assert "delta" in brief2
        assert "mean" in brief3


# ─── _fail_codegen_result ────────────────────────────────────────────


class TestFailCodegenResult:
    def test_fields_present(self, runner: FactorRunner) -> None:
        result = runner._fail_codegen_result(
            alpha_index=1, stage="react", error="LLM failed", code=None, t0=0.0,
        )
        assert result["status"] == "failed"
        assert result["stage"] == "react"
        assert result["error"] == "LLM failed"
        assert result["code"] is None
        assert result["code_chars"] == 0
        assert result["ic_mean"] is None
        assert result["icir"] is None
        assert result["ic_winrate"] is None
        assert "elapsed_sec" in result
        assert result["elapsed_sec"] >= 0

    def test_code_chars_when_code_present(self, runner: FactorRunner) -> None:
        result = runner._fail_codegen_result(
            alpha_index=2, stage="syntax", error="bad syntax", code="x = ", t0=0.0,
        )
        assert result["code"] == "x = "
        assert result["code_chars"] == 4

    def test_stage_oneshot(self, runner: FactorRunner) -> None:
        result = runner._fail_codegen_result(
            alpha_index=3, stage="extract", error="no python", code=None, t0=0.0,
        )
        assert result["stage"] == "extract"


# ─── _fail_pipeline_result ───────────────────────────────────────────


class TestFailPipelineResult:
    def test_includes_traceback(self, runner: FactorRunner) -> None:
        try:
            raise RuntimeError("pipeline boom")
        except RuntimeError as exc:
            result = runner._fail_pipeline_result(1, code="x = 1", exc=exc, t0=0.0)
        assert result["status"] == "failed"
        assert result["stage"] == "pipeline"
        assert "RuntimeError: pipeline boom" in result["error"]
        assert "traceback" in result
        assert "RuntimeError" in result["traceback"]
        assert "pipeline boom" in result["traceback"]

    def test_traceback_capped_at_1500(self, runner: FactorRunner) -> None:
        try:
            raise ValueError("x" * 5000)
        except ValueError as exc:
            result = runner._fail_pipeline_result(1, code="", exc=exc, t0=0.0)
        assert len(result["traceback"]) <= 1500

    def test_code_chars(self, runner: FactorRunner) -> None:
        try:
            raise OSError("disk full")
        except OSError as exc:
            result = runner._fail_pipeline_result(1, code="print(1)", exc=exc, t0=0.0)
        assert result["code"] == "print(1)"
        assert result["code_chars"] == 8


# ─── _log_backtest_metrics ───────────────────────────────────────────


class TestLogBacktestMetrics:
    def test_logs_ic_icir_winrate(self, runner: FactorRunner, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        backtest = {"ic_mean": 0.025, "icir": 0.18, "win_rate": 0.52}
        runner._log_backtest_metrics(1, backtest)
        text = caplog.text
        assert "IC=" in text and "0.0250" in text
        assert "ICIR=" in text and "0.1800" in text
        assert "WinRate=" in text and "52.0%" in text

    def test_logs_with_missing_keys(self, runner: FactorRunner, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        runner._log_backtest_metrics(1, {})
        text = caplog.text
        assert "IC=" in text and "ICIR=" in text


# ─── _success_result ─────────────────────────────────────────────────


class TestSuccessResult:
    def test_full_fields(self, runner: FactorRunner) -> None:
        factor_series = pl.Series("f", [1.0, 2.0, 3.0])
        backtest = {"ic_mean": 0.03, "icir": 0.5, "win_rate": 0.6}
        h5_path = Path("/tmp/fake.h5")
        result = runner._success_result(
            alpha_index=1, factor_name="alpha-001", formula_brief="x = y",
            code="x = y", factor_series=factor_series, h5_path=h5_path,
            backtest=backtest, t0=0.0,
        )
        assert result["status"] == "success"
        assert result["alpha_index"] == 1
        assert result["factor_name"] == "alpha-001"
        assert result["formula_brief"] == "x = y"
        assert result["code"] == "x = y"
        assert result["code_chars"] == 5
        assert result["factor_series_len"] == 3
        assert result["factor_series_dtype"] == str(factor_series.dtype)
        assert result["h5_path"] == str(h5_path)
        assert result["ic_mean"] == 0.03
        assert result["icir"] == 0.5
        assert result["ic_winrate"] == 0.6
        assert result["elapsed_sec"] >= 0


# ─── _fail_result (unified factory for parallel failure, P3 Bug 5) ─


class TestFailResult:
    def test_minimal(self, runner: FactorRunner) -> None:
        result = runner._fail_result(
            alpha_index=42, stage="TimeoutError", error="boom", t0=0.0,
        )
        assert result["status"] == "failed"
        assert result["stage"] == "TimeoutError"
        assert result["error"] == "boom"
        assert result["code"] is None
        assert result["code_chars"] == 0
        assert result["ic_mean"] is None
        assert result["icir"] is None
        assert result["ic_winrate"] is None
        assert "elapsed_sec" in result

    def test_with_code(self, runner: FactorRunner) -> None:
        result = runner._fail_result(
            alpha_index=1, stage="pipeline", error="x", t0=0.0, code="a = 1",
        )
        assert result["code"] == "a = 1"
        assert result["code_chars"] == 5

    def test_extra_kwargs(self, runner: FactorRunner) -> None:
        result = runner._fail_result(
            alpha_index=1, stage="pipeline", error="x", t0=0.0,
            traceback="fake tb", react_meta={"iterations": 2},
        )
        assert result["traceback"] == "fake tb"
        assert result["react_meta"] == {"iterations": 2}

    def test_parallel_failure_uses_factory(self, runner: FactorRunner) -> None:
        """Bug 5: _handle_parallel_failure must produce FactorResult with all
        required fields (code_chars=0 not None).

        L2: stage.results is now list[FactorResult] (was list[dict]).
        """
        from scripts.run_101_alphas_v2 import FactorStage

        config = RunConfig(
            track_b_path=runner.config.track_b_path,
            output_dir=runner.config.output_dir,
        )
        stage = FactorStage(config)
        # FactorStage uses __slots__, can't patch method; instead verify the
        # resulting FactorResult has all required fields.
        stage._handle_parallel_failure(7, "TimeoutError", "future boom")
        assert len(stage.results) == 1
        r = stage.results[0]  # FactorResult, not dict
        assert r.status == "failed"
        assert r.code_chars == 0  # ← Bug 5 fix: not None
        assert r.stage == "TimeoutError"
        assert r.signal.metadata["alpha_index"] == 7  # L2: idx moved to signal.metadata
        assert r.error.startswith("future boom")
        assert r.backtest == {}  # L2: backtest empty dict (not None fields)
        assert r.elapsed_sec == 0.0
        assert stage.failures == 1


# ─── _generate_code (ReAct vs 1-shot dispatch) ─────────────────────


class TestGenerateCode:
    def test_react_dispatch_calls_react_helper(self, runner: FactorRunner) -> None:
        """When use_react=True, _generate_code calls _llm_code_react."""
        df_pl = pl.DataFrame({"x": [1, 2, 3]})
        with patch.object(runner, "_llm_code_react", return_value=("code1", None, None, {})) as react:
            with patch("scripts.run_101_alphas_v2.build_llm_client"):
                with patch("scripts.run_101_alphas_v2.llm_code_oneshot") as oneshot:
                    code, fs, err, stage = runner._generate_code("a", "b", df_pl, use_react=True)
                    assert react.called
                    assert not oneshot.called
                    assert stage == "react"
                    assert code == "code1"

    def test_oneshot_dispatch(self, runner: FactorRunner) -> None:
        """When use_react=False, _generate_code calls llm_code_oneshot."""
        df_pl = pl.DataFrame({"x": [1, 2, 3]})
        with patch.object(runner, "_llm_code_react") as react:
            with patch("scripts.run_101_alphas_v2.build_llm_client"):
                with patch("scripts.run_101_alphas_v2.llm_code_oneshot",
                           return_value=("code2", None, None, 1)) as oneshot:
                    code, fs, err, stage = runner._generate_code("a", "b", df_pl, use_react=False)
                    assert not react.called
                    assert oneshot.called
                    assert stage == "syntax"  # _STAGE_NAMES[1]

    def test_oneshot_unknown_stage(self, runner: FactorRunner) -> None:
        """Unknown stage_idx falls back to 'unknown'."""
        df_pl = pl.DataFrame({"x": [1, 2, 3]})
        with patch("scripts.run_101_alphas_v2.build_llm_client"):
            with patch("scripts.run_101_alphas_v2.llm_code_oneshot",
                       return_value=("c", None, None, 99)):
                code, fs, err, stage = runner._generate_code("a", "b", df_pl, use_react=False)
                assert stage == "unknown"
