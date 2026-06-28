"""Tests for top-level llm_code_react (P2 refactor).

Covers:
  - llm_code_react: returns (code, factor_series, error, react_meta)
  - _ReActProgressHook: prints iteration progress
  - error path: result.error → (None, None, error, meta)
  - success path: result.code → (code, factor_series, None, meta)
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from scripts.run_101_alphas_v2 import (
    RunConfig,
    _ReActProgressHook,
    llm_code_react,
)

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path) -> RunConfig:
    return RunConfig(
        track_b_path=tmp_path / "track_b.json",
        max_repair_rounds=3,
        temperature=0.3,
    )


def _make_unified_result(
    code: str | None = "print(1)",
    factor_series: pl.Series | None = None,
    error: str | None = None,
    iterations: int = 1,
    stop_reason: str = "success",
) -> Any:
    """Mock UnifiedResult returned by generate_factor_code_sync."""
    r = MagicMock()
    r.code = code
    r.factor_series = factor_series
    r.error = error
    r.iterations = iterations
    r.stop_reason = stop_reason
    r.to_dict = lambda: {
        "code": code,
        "iterations": iterations,
        "stop_reason": stop_reason,
        "error": error,
    }
    return r


# ─── llm_code_react success path ────────────────────────────────────


class TestLLMCodeReactSuccess:
    def test_returns_code_and_factor_series(self, config: RunConfig) -> None:
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0, 2.0, 3.0])
        mock_result = _make_unified_result(code="x = y", factor_series=fs)

        with patch(
            "llmwikify.apps.chat.agent.unified.pipelines.codegen.generate_factor_code_sync",
            return_value=mock_result,
        ) as gen:
            code, factor_series, error, meta = llm_code_react(
                "alpha-001", "x = y", df, llm=MagicMock(), config=config,
            )

        assert code == "x = y"
        assert factor_series is fs
        assert error is None
        assert meta["stop_reason"] == "success"
        gen.assert_called_once()

    def test_passes_config_to_unified(self, config: RunConfig) -> None:
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0])
        mock_result = _make_unified_result(code="x", factor_series=fs)

        with patch(
            "llmwikify.apps.chat.agent.unified.pipelines.codegen.generate_factor_code_sync",
            return_value=mock_result,
        ) as gen:
            llm_code_react("a", "b", df, llm=MagicMock(), config=config)

        # Verify config fields are forwarded
        kwargs = gen.call_args.kwargs
        assert kwargs["max_repair_rounds"] == 3
        assert kwargs["temperature"] == 0.3
        assert isinstance(kwargs["hook"], _ReActProgressHook)


# ─── llm_code_react error path ──────────────────────────────────────


class TestLLMCodeReactError:
    def test_returns_none_code_when_error(self, config: RunConfig) -> None:
        df = pl.DataFrame({"x": [1, 2, 3]})
        mock_result = _make_unified_result(code=None, factor_series=None,
                                            error="LLM boom", stop_reason="max_iter")

        with patch(
            "llmwikify.apps.chat.agent.unified.pipelines.codegen.generate_factor_code_sync",
            return_value=mock_result,
        ):
            code, factor_series, error, meta = llm_code_react(
                "alpha-001", "x = y", df, llm=MagicMock(), config=config,
            )

        assert code is None
        assert factor_series is None
        assert error == "LLM boom"
        assert meta["stop_reason"] == "max_iter"


# ─── _ReActProgressHook ─────────────────────────────────────────────


class TestReActProgressHook:
    def test_on_reason_start_logs_iteration(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        hook = _ReActProgressHook()
        ctx = MagicMock(iteration=3)
        hook.on_reason_start(ctx)
        assert "[REASON] iteration 3" in caplog.text

    def test_on_act_end_success(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        hook = _ReActProgressHook()
        result = MagicMock(success=True, error_kind="none")
        hook.on_act_end(MagicMock(), result)
        assert "[ACT] OK (none)" in caplog.text

    def test_on_act_end_failure(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="run_101_alphas_v2")
        hook = _ReActProgressHook()
        result = MagicMock(spec=["success", "error_kind", "error"])
        result.success = False
        result.error_kind = "syntax"
        result.error = "SyntaxError: invalid syntax"
        hook.on_act_end(MagicMock(), result)
        assert "[ACT] syntax" in caplog.text
        assert "SyntaxError" in caplog.text
