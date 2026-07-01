"""Tests for PR8 L1: ReAct codegen runner (moved from v2 to src/).

Covers:
  - ReActProgressHook.on_reason_start: log [REASON] iteration N
  - ReActProgressHook.on_act_end: success path
  - ReActProgressHook.on_act_end: failure path
  - llm_code_react: success → (code, factor_series, None, meta)
  - llm_code_react: error → (None, None, error, meta)
  - llm_code_react: kwargs override defaults

Total: ~10 tests.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from llmwikify.reproduction.codegen.react_runner import (
    ReActProgressHook,
    llm_code_react,
)


def _make_unified_result(code=None, factor_series=None, error=None, stop_reason="success"):
    """Build a fake UnifiedResult for mocking."""
    r = MagicMock()
    r.code = code
    r.factor_series = factor_series
    r.error = error
    r.stop_reason = stop_reason
    r.iterations = 1
    r.to_dict = MagicMock(return_value={
        "code": code, "error": error, "iterations": 1, "stop_reason": stop_reason,
    })
    return r


# ─── ReActProgressHook ────────────────────────────────────────────────


class TestReActProgressHook:
    def test_on_reason_start_logs_iteration(self, caplog) -> None:
        hook = ReActProgressHook()
        ctx = MagicMock(iteration=3)
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.codegen.react_runner"):
            hook.on_reason_start(ctx)
        assert any("[REASON] iteration 3" in r.message for r in caplog.records)

    def test_on_act_end_success(self, caplog) -> None:
        hook = ReActProgressHook()
        ctx = MagicMock()
        result = MagicMock(success=True, error_kind="none")
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.codegen.react_runner"):
            hook.on_act_end(ctx, result)
        assert any("[ACT] OK" in r.message for r in caplog.records)

    def test_on_act_end_failure(self, caplog) -> None:
        hook = ReActProgressHook()
        ctx = MagicMock()
        result = MagicMock(success=False, error_kind="timeout", error="LLM timeout")
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.codegen.react_runner"):
            hook.on_act_end(ctx, result)
        assert any("[ACT] timeout" in r.message for r in caplog.records)
        assert any("LLM timeout" in r.message for r in caplog.records)

    def test_on_act_end_handles_missing_attrs(self, caplog) -> None:
        """Hook should not crash on objects missing `success` or `error_kind`."""
        hook = ReActProgressHook()
        ctx = MagicMock(spec=[])  # no attributes
        result = MagicMock(spec=[])  # no attributes
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.codegen.react_runner"):
            hook.on_act_end(ctx, result)
        # Should log something (with default values)
        assert len(caplog.records) >= 1


# ─── llm_code_react ──────────────────────────────────────────────────


class TestLLMCodeReact:
    def test_success_path(self) -> None:
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0, 2.0, 3.0])
        mock_result = _make_unified_result(code="x = 1", factor_series=fs)

        with patch(
            "llmwikify.kernel.agent.generate_factor_code_sync",
            return_value=mock_result,
        ) as gen:
            code, factor_series, error, meta = llm_code_react(
                "alpha-001", "x = y", df, llm=MagicMock(),
            )

        assert code == "x = 1"
        assert factor_series is fs
        assert error is None
        assert meta["stop_reason"] == "success"
        gen.assert_called_once()

    def test_error_path(self) -> None:
        df = pl.DataFrame({"x": [1, 2, 3]})
        mock_result = _make_unified_result(
            code=None, factor_series=None, error="LLM boom", stop_reason="max_iter",
        )

        with patch(
            "llmwikify.kernel.agent.generate_factor_code_sync",
            return_value=mock_result,
        ):
            code, factor_series, error, meta = llm_code_react(
                "alpha-001", "x = y", df, llm=MagicMock(),
            )

        assert code is None
        assert factor_series is None
        assert error == "LLM boom"
        assert meta["stop_reason"] == "max_iter"

    def test_default_kwargs(self) -> None:
        """max_repair_rounds=3, temperature=0.3 are the defaults."""
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0])
        mock_result = _make_unified_result(code="x", factor_series=fs)

        with patch(
            "llmwikify.kernel.agent.generate_factor_code_sync",
            return_value=mock_result,
        ) as gen:
            llm_code_react("a", "b", df, llm=MagicMock())

        kwargs = gen.call_args.kwargs
        assert kwargs["max_repair_rounds"] == 3
        assert kwargs["temperature"] == 0.3
        assert isinstance(kwargs["hook"], ReActProgressHook)

    def test_custom_kwargs(self) -> None:
        """Caller can override max_repair_rounds and temperature."""
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0])
        mock_result = _make_unified_result(code="x", factor_series=fs)

        with patch(
            "llmwikify.kernel.agent.generate_factor_code_sync",
            return_value=mock_result,
        ) as gen:
            llm_code_react("a", "b", df, llm=MagicMock(),
                           max_repair_rounds=5, temperature=0.7)

        kwargs = gen.call_args.kwargs
        assert kwargs["max_repair_rounds"] == 5
        assert kwargs["temperature"] == 0.7

    def test_logs_unified_summary(self, caplog) -> None:
        """Should log iterations / stop_reason / error after generate_factor_code_sync."""
        df = pl.DataFrame({"x": [1, 2, 3]})
        fs = pl.Series("f", [1.0])
        mock_result = _make_unified_result(
            code="x", factor_series=fs, stop_reason="success",
        )

        with patch(
            "llmwikify.kernel.agent.generate_factor_code_sync",
            return_value=mock_result,
        ):
            with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.codegen.react_runner"):
                llm_code_react("a", "b", df, llm=MagicMock())

        assert any("iterations=" in r.message for r in caplog.records)
        assert any("stop_reason=" in r.message for r in caplog.records)
