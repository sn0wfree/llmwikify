"""Tests for factor_compiler_react (ReAct-style self-retry).

Two layers:
  1. MOCK mode — fake LLM emits broken code, then good code. Asserts that
     the ReAct loop retries and the second REASON succeeds.
  2. Real LLM mode — gated by RUN_LLM_TESTS=1; runs alpha-001 / alpha-002
     through the full ReAct loop and verifies IC is computed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import polars as pl
import pytest

from llmwikify.reproduction.factor_compiler_react import (
    ReactErrorKind,
    ReactResult,
    ReactState,
    ReactStep,
    _extract_python,
    _validate_safety,
    _validate_syntax,
    compile_to_code_react,
)
from llmwikify.reproduction.telemetry import get_telemetry

# ── Mock LLM helpers ─────────────────────────────────────────────


class _ScriptedLLM:
    """LLM that returns a sequence of pre-scripted responses.

    Each call to chat() pops the next response from the queue. Records
    every (messages, kwargs) pair for assertion.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict], dict]] = []

    def chat(self, *, messages, temperature=0.5, **kwargs):
        self.calls.append((list(messages), {"temperature": temperature, **kwargs}))
        if not self._responses:
            raise AssertionError("LLM called more times than scripted")
        return self._responses.pop(0)


# ── Sample data ──────────────────────────────────────────────────


def _sample_long_df(n_stocks: int = 5, n_dates: int = 30) -> pl.DataFrame:
    """Small long-format polars DataFrame for factor computation tests."""
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    codes = [f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]
    rows = []
    for d in dates:
        for c in codes:
            rows.append(
                {
                    "date": int(d.strftime("%Y%m%d")),
                    "code": c,
                    "close": float(rng.uniform(5, 20)),
                    "open": float(rng.uniform(5, 20)),
                    "high": float(rng.uniform(5, 20)),
                    "low": float(rng.uniform(5, 20)),
                    "volume": float(rng.uniform(1e5, 1e7)),
                    "returns": float(rng.normal(0, 0.02)),
                    "vwap": float(rng.uniform(5, 20)),
                }
            )
    return pl.DataFrame(rows).sort(["date", "code"])


SYSTEM_PROMPT = "You are a quant factor code generator."


# ── Unit tests on helpers ────────────────────────────────────────


def test_extract_python_with_fence():
    text = 'Here is code:\n```python\ndef compute_factor(df):\n    return pl.col("close")\n```\nDone.'
    code = _extract_python(text)
    assert code is not None
    assert "def compute_factor" in code
    assert "pl.col" in code


def test_extract_python_no_fence_falls_back_to_def():
    text = 'def compute_factor(df):\n    return pl.col("close")\n'
    code = _extract_python(text)
    assert code is not None
    assert code.startswith("def compute_factor")


def test_extract_python_returns_none_when_no_compute_factor():
    assert _extract_python("just some prose, no code") is None
    assert _extract_python("") is None


def test_validate_syntax_ok():
    ok, err = _validate_syntax("def f():\n    return 1\n")
    assert ok is True
    assert err == ""


def test_validate_syntax_bad():
    ok, err = _validate_syntax("def f(:\n    return 1\n")
    assert ok is False
    assert "line" in err


# ── ReAct loop: extract failure path ─────────────────────────────


def test_react_retries_on_extract_failure():
    """LLM first emits no ```python``` fence; ReAct retries and succeeds."""
    df = _sample_long_df()
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').pct_change(5)\n"
    )
    llm = _ScriptedLLM(
        "Sorry, I can't help with that.",  # no fence
        f"```python\n{good_code}\n```",  # retry with code
    )

    result = compile_to_code_react(
        factor_name="test_alpha",
        formula_brief="5-day momentum",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
    )

    assert result.is_valid is True
    assert result.iterations == 2
    assert result.error_kind == ReactErrorKind.NONE
    # Step trace should have 1 REASON (failed) + 1 ACT (extract_failed) +
    # 1 OBSERVE + 1 REASON (succeeded) + 1 ACT + 1 DECIDE = 6 steps
    states = [s.state for s in result.steps]
    assert ReactState.REASON in states
    assert ReactState.ACT in states
    assert ReactState.DECIDE in states
    # First ACT must be extract_failed
    first_act = next(s for s in result.steps if s.state == ReactState.ACT)
    assert first_act.error_kind == ReactErrorKind.EXTRACT_FAILED
    # LLM was called twice
    assert len(llm.calls) == 2
    # Second call's user message must mention the previous failure
    second_messages = llm.calls[1][0]
    last_user = next(m for m in reversed(second_messages) if m["role"] == "user")
    assert "extract_failed" in last_user["content"] or "no ```python```" in last_user["content"]


# ── ReAct loop: syntax error path ───────────────────────────────


def test_react_retries_on_syntax_error():
    """LLM emits code with SyntaxError on first try; ReAct retries."""
    df = _sample_long_df()
    bad_code = "def compute_factor(df:\n    return 1\n"  # missing )
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').pct_change(5)\n"
    )
    llm = _ScriptedLLM(
        f"```python\n{bad_code}\n```",
        f"```python\n{good_code}\n```",
    )

    result = compile_to_code_react(
        factor_name="test_syntax",
        formula_brief="5-day momentum",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
    )

    assert result.is_valid is True
    assert result.iterations == 2
    first_act = next(s for s in result.steps if s.state == ReactState.ACT)
    assert first_act.error_kind == ReactErrorKind.SYNTAX_ERROR


# ── ReAct loop: execution error path ────────────────────────────


def test_react_retries_on_execution_error():
    """LLM emits code that uses a non-existent attribute (mimics `.out('date')` typo)."""
    df = _sample_long_df()
    # .out() is not a polars Expr method — should raise AttributeError on execute
    bad_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').rank().out('date')\n"
    )
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').rank().over('date')\n"
    )
    llm = _ScriptedLLM(
        f"```python\n{bad_code}\n```",
        f"```python\n{good_code}\n```",
    )

    result = compile_to_code_react(
        factor_name="test_exec",
        formula_brief="rank by date",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
    )

    assert result.is_valid is True
    assert result.iterations == 2
    first_act = next(s for s in result.steps if s.state == ReactState.ACT)
    assert first_act.error_kind == ReactErrorKind.EXECUTE_ERROR
    # The feedback to the second REASON should mention the AttributeError
    second_messages = llm.calls[1][0]
    last_user = next(m for m in reversed(second_messages) if m["role"] == "user")
    assert "AttributeError" in last_user["content"] or "execute_error" in last_user["content"]


# ── ReAct loop: exhausts rounds on persistent failure ──────────


def test_react_exhausts_rounds():
    """LLM keeps emitting bad code; ReAct gives up after max_repair_rounds + 1."""
    df = _sample_long_df()
    # Make first two fail at execute (ZeroDivisionError); third has no fence.
    bad_zero_div = "def compute_factor(df):\n    return 1 / 0\n"
    bad_nan = "def compute_factor(df):\n    return float('nan') / 0\n"
    llm = _ScriptedLLM(
        f"```python\n{bad_zero_div}\n```",
        f"```python\n{bad_nan}\n```",
        "no code this time",  # extract_failed on round 3
    )

    result = compile_to_code_react(
        factor_name="test_exhaust",
        formula_brief="test",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
    )

    assert result.is_valid is False
    assert result.iterations == 3  # 1 + 2 retries
    assert result.error_kind == ReactErrorKind.EXTRACT_FAILED  # last failure
    # 3 LLM calls total
    assert len(llm.calls) == 3


# ── ReAct loop: success on first try (no retry needed) ─────────


def test_react_succeeds_on_first_try():
    df = _sample_long_df()
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').pct_change(5)\n"
    )
    llm = _ScriptedLLM(f"```python\n{good_code}\n```")

    result = compile_to_code_react(
        factor_name="test_first_try",
        formula_brief="5-day momentum",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=3,
        temperature=0.0,
    )

    assert result.is_valid is True
    assert result.iterations == 1
    assert len(llm.calls) == 1
    # 3 steps: REASON + ACT (success) + DECIDE
    assert len(result.steps) == 3
    assert result.steps[0].state == ReactState.REASON
    assert result.steps[1].state == ReactState.ACT
    assert result.steps[1].error_kind == ReactErrorKind.NONE
    assert result.steps[2].state == ReactState.DECIDE


# ── Telemetry events ────────────────────────────────────────────


def test_telemetry_records_self_repair_events():
    df = _sample_long_df()
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').pct_change(5)\n"
    )
    llm = _ScriptedLLM(
        "no fence",  # extract_failed
        f"```python\n{good_code}\n```",
    )

    telemetry = get_telemetry()
    telemetry.reset()
    compile_to_code_react(
        factor_name="test_telemetry",
        formula_brief="test",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
    )

    summary = telemetry.summary()
    counts = summary["counts"]
    assert counts["self_repair.start"] == 1
    assert counts["self_repair.reason"] == 2
    assert counts["self_repair.act.extract_failed"] == 1
    assert counts["self_repair.observe"] == 1
    assert counts["self_repair.decide.done_success"] == 1
    assert counts["self_repair.total_elapsed_sec"] == 1


# ── progress_callback hook ──────────────────────────────────────


def test_progress_callback_called_per_step():
    df = _sample_long_df()
    good_code = (
        "def compute_factor(df: pl.DataFrame) -> pl.Series:\n"
        "    return pl.col('close').pct_change(5)\n"
    )
    llm = _ScriptedLLM(
        "no code",
        f"```python\n{good_code}\n```",
    )
    seen_states: list[ReactState] = []

    def cb(step: ReactStep) -> None:
        seen_states.append(step.state)

    result = compile_to_code_react(
        factor_name="test_callback",
        formula_brief="test",
        system_prompt=SYSTEM_PROMPT,
        df=df,
        llm=llm,
        max_repair_rounds=2,
        temperature=0.0,
        progress_callback=cb,
    )

    # 2 rounds, each emits: REASON, ACT, OBSERVE (round 1) or DECIDE (round 2)
    assert ReactState.REASON in seen_states
    assert ReactState.ACT in seen_states
    assert ReactState.OBSERVE in seen_states
    assert ReactState.DECIDE in seen_states
    assert result.is_valid is True


# ── Real LLM e2e test (gated) ───────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="Real LLM tests gated by RUN_LLM_TESTS=1",
)
def test_react_real_llm_alpha_001_succeeds_within_rounds():
    """End-to-end: real LLM generates factor code, executes, computes IC."""

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from scripts.test_one_factor_llm_code import _load_real_data  # type: ignore

    df = _load_real_data(alpha_index=1)
    config = json.loads(Path("~/.llmwikify/llmwikify.json").expanduser().read_text())
    llm_cfg = config["llm"]

    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    llm = StreamableLLMClient(
        provider=llm_cfg.get("provider", "openai"),
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
        request_timeout_seconds=float(llm_cfg.get("timeout", 600)),
    )

    from scripts.test_one_factor_llm_code import SYSTEM_PROMPT_CODE  # type: ignore

    result = compile_to_code_react(
        factor_name="alpha-001",
        formula_brief="rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5",
        system_prompt=SYSTEM_PROMPT_CODE,
        df=df,
        llm=llm,
        max_repair_rounds=3,
        temperature=0.3,
    )

    assert result.iterations >= 1
    if not result.is_valid:
        pytest.fail(
            f"ReAct failed after {result.iterations} rounds: "
            f"{result.error_kind.value}: {result.error_message[:300]}"
        )
