"""ReAct-style self-retry factor compiler (Loop v4 Code Path).

Borrowed state machine pattern from llmwikify/apps/chat/agent/runner_v2.py
(``ChatRunnerV2`` with PRECHECK/REASON/ACT/OBSERVE/FINALIZE), but specialised
for the factor-code-generation task:

  REASON  → LLM call (StreamableLLMClient.chat, same as runner_v2._reason)
  ACT     → extract ```python``` + ast.parse + CodeSandbox.validate + execute
  OBSERVE → classify outcome: success / extract_failed / syntax_error / safety_error / execute_error
  DECIDE  → on success return CompileResult; on error inject message, loop

This addresses the "LLM 打错字" failure mode observed in stage C e2e (alpha-001
LLM output used ``.out('date')`` instead of ``.over('date')``). Pure mechanical
self-repair (PR-6) cannot fix LLM typos — only an LLM-side re-emit can.

Reuse vs. duplication:
  * ``StreamableLLMClient.chat`` — same interface runner_v2 uses internally
  * ``CodeSandbox`` from ``QuantNodes.ai.sandbox`` — same as ``_compute_factor_from_code``
  * ``QuantNodes.operators.proxy.{list_operators, get_operator}`` — same as factor_backtest
  * ``Telemetry`` from ``.telemetry`` — same singleton runner_v2 doesn't use (yet)

Phase B (2026-06-22): initial implementation, tested on alpha-001 / alpha-002.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import polars as pl

from ..common.telemetry import get_telemetry
from .llm_code import (
    _PYTHON_FENCE_RE,
    build_execute_namespace,
    execute_code,
    extract_python,
    validate_safety,
    validate_syntax,
)

# Backward-compatible aliases for existing test imports
_extract_python = extract_python
_validate_syntax = validate_syntax
_validate_safety = validate_safety
_build_execute_namespace = build_execute_namespace
_execute_code = execute_code

logger = logging.getLogger(__name__)


# ── State machine ─────────────────────────────────────────────────


class ReactState(str, Enum):
    """ReAct loop states (mirrors runner_v2's _StateTrace labels)."""
    REASON = "REASON"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"
    DONE = "DONE"


class ReactErrorKind(str, Enum):
    """Categorised ACT/OBSERVE outcomes."""
    NONE = "none"  # success
    EXTRACT_FAILED = "extract_failed"  # no ```python``` fence
    SYNTAX_ERROR = "syntax_error"  # ast.parse failed
    SAFETY_ERROR = "safety_error"  # CodeSandbox.validate failed
    EXECUTE_ERROR = "execute_error"  # CodeSandbox.execute raised
    OUTPUT_INVALID = "output_invalid"  # result is not a polars.Series


@dataclass
class ReactStep:
    """One iteration of the ReAct loop (state + outcome)."""
    state: ReactState
    error_kind: ReactErrorKind = ReactErrorKind.NONE
    error_message: str = ""
    code: str = ""  # extracted code (may be empty on extract_failed)
    elapsed_sec: float = 0.0


@dataclass
class ReactResult:
    """Final result of ``compile_to_code_react``."""
    code: str  # the LLM-emitted Python source (empty on total failure)
    is_valid: bool
    error_kind: ReactErrorKind = ReactErrorKind.NONE
    error_message: str = ""
    iterations: int = 0  # number of LLM calls (REASON invocations)
    steps: list[ReactStep] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "is_valid": self.is_valid,
            "error_kind": self.error_kind.value,
            "error_message": self.error_message,
            "iterations": self.iterations,
            "steps": [
                {
                    "state": s.state.value,
                    "error_kind": s.error_kind.value,
                    "error_message": s.error_message,
                    "code_chars": len(s.code),
                    "code": s.code,
                    "elapsed_sec": round(s.elapsed_sec, 3),
                }
                for s in self.steps
            ],
            "elapsed_sec": round(self.elapsed_sec, 3),
        }


# ── Code extraction & validation helpers ──────────────────────────





# ── ReAct driver ─────────────────────────────────────────────────


# Prompt template for the OBSERVE → REASON error feedback. Mirrors the
# pattern runner_v2.py uses to inject tool errors back into the message
# history (see ``_reason`` around line 415).
from .feedback_templates import (
    OBSERVE_FEEDBACK_TEMPLATE,  # noqa: F401 — backward compat re-export
)


def compile_to_code_react(
    factor_name: str,
    formula_brief: str,
    system_prompt: str,
    *,
    df: pl.DataFrame,
    llm: Any,
    max_repair_rounds: int = 3,
    temperature: float = 0.5,
    progress_callback: Callable[[ReactStep], None] | None = None,
) -> ReactResult:
    """ReAct-style self-retry: LLM emits code → execute → on error, re-prompt.

    .. deprecated::
        Use ``llmwikify.kernel.agent.generate_factor_code_sync`` instead.

    Args:
        factor_name: Display name (for logging / telemetry).
        formula_brief: The factor's natural-language formula.
        system_prompt: SYSTEM_PROMPT_CODE template.
        df: Polars DataFrame (long format) passed as ``df`` to compute_factor.
        llm: LLM client with ``chat(messages, temperature=...)`` (StreamableLLMClient or compatible).
        max_repair_rounds: Total REASON invocations = 1 (initial) + max_repair_rounds (retries).
        temperature: LLM sampling temperature.
        progress_callback: Optional hook invoked after each step (for streaming).

    Returns:
        ReactResult with code, is_valid, error_kind, full step trace.

    Telemetry events emitted:
        - self_repair.reason (per LLM call)
        - self_repair.act.success / .extract_failed / .syntax_error / .safety_error
        - self_repair.observe.<kind>  (per observed outcome)
        - self_repair.decide.retry / .done_success / .done_failure
        - self_repair.total_elapsed_sec
    """
    import warnings
    warnings.warn(
        "compile_to_code_react is deprecated. Use "
        "llmwikify.kernel.agent.generate_factor_code_sync instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    t0 = time.monotonic()
    telemetry = get_telemetry()
    telemetry.record("self_repair.start", factor=factor_name)

    user_prompt = f"""Factor: {factor_name}
Formula (pseudo-code): {formula_brief}

Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series` that computes
this factor. Use QuantNodes operators (rank, ts_argmax, rolling_std, etc.) which are
in the namespace, and use polars expressions otherwise.

Output ONLY the code block (use FUNCTION FORM for QuantNodes operators)."""

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    steps: list[ReactStep] = []
    last_error_kind = ReactErrorKind.NONE
    last_error_message = ""
    final_code = ""
    is_valid = False
    iterations = 0

    for round_idx in range(max_repair_rounds + 1):
        # ── REASON: LLM call ──
        iterations = round_idx + 1
        t_reason = time.monotonic()
        try:
            response = llm.chat(messages=messages, temperature=temperature)
        except Exception as exc:
            err_str = f"{type(exc).__name__}: {exc}"
            step = ReactStep(
                state=ReactState.REASON,
                error_kind=ReactErrorKind.EXECUTE_ERROR,
                error_message=err_str,
                elapsed_sec=time.monotonic() - t_reason,
            )
            steps.append(step)
            telemetry.record("self_repair.reason.exception", factor=factor_name, error=err_str[:200])
            last_error_kind = ReactErrorKind.EXECUTE_ERROR
            last_error_message = err_str
            # LLM-side failure is hard to recover from via re-prompt; break
            break

        messages.append({"role": "assistant", "content": response})
        step = ReactStep(
            state=ReactState.REASON,
            code=response,
            elapsed_sec=time.monotonic() - t_reason,
        )
        steps.append(step)
        telemetry.record(
            "self_repair.reason",
            factor=factor_name,
            iteration=iterations,
            response_chars=len(response),
        )
        if progress_callback:
            progress_callback(step)

        # ── ACT: extract → validate → execute (always emitted) ──
        t_act = time.monotonic()
        new_code = _extract_python(response)
        if new_code is None:
            _record_act_failure(
                steps, progress_callback, factor_name, iterations,
                ReactErrorKind.EXTRACT_FAILED,
                "no ```python``` fence in response and no `def compute_factor` found",
                "", t_act,
            )
            _observe_and_decide(
                ReactErrorKind.EXTRACT_FAILED,
                "no ```python``` fence in response and no `def compute_factor` found",
                messages, steps, progress_callback, factor_name, iterations,
            )
            last_error_kind = ReactErrorKind.EXTRACT_FAILED
            last_error_message = "no ```python``` fence"
            continue

        syntax_ok, syntax_err = _validate_syntax(new_code)
        if not syntax_ok:
            kind = ReactErrorKind.SYNTAX_ERROR
            msg = f"SyntaxError: {syntax_err}"
            _record_act_failure(
                steps, progress_callback, factor_name, iterations, kind, msg, new_code, t_act,
            )
            _observe_and_decide(kind, msg, messages, steps, progress_callback, factor_name, iterations, new_code)
            last_error_kind, last_error_message = kind, msg
            continue

        safety_ok, safety_err = _validate_safety(new_code)
        if not safety_ok:
            kind = ReactErrorKind.SAFETY_ERROR
            msg = f"CodeSandbox rejected: {safety_err}"
            _record_act_failure(
                steps, progress_callback, factor_name, iterations, kind, msg, new_code, t_act,
            )
            _observe_and_decide(kind, msg, messages, steps, progress_callback, factor_name, iterations, new_code)
            last_error_kind, last_error_message = kind, msg
            continue

        try:
            factor_series = _execute_code(new_code, df)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            kind = ReactErrorKind.EXECUTE_ERROR
            msg = f"{type(exc).__name__}: {exc}\n{tb}"
            _record_act_failure(
                steps, progress_callback, factor_name, iterations, kind, msg, new_code, t_act,
            )
            _observe_and_decide(kind, msg, messages, steps, progress_callback, factor_name, iterations, new_code)
            last_error_kind, last_error_message = kind, msg
            continue

        if not isinstance(factor_series, pl.Series):
            kind = ReactErrorKind.OUTPUT_INVALID
            msg = f"compute_factor returned {type(factor_series).__name__}, expected pl.Series"
            _record_act_failure(
                steps, progress_callback, factor_name, iterations, kind, msg, new_code, t_act,
            )
            _observe_and_decide(kind, msg, messages, steps, progress_callback, factor_name, iterations, new_code)
            last_error_kind, last_error_message = kind, msg
            continue

        # ── ACT success (no error_kind) ──
        act_step = ReactStep(
            state=ReactState.ACT,
            code=new_code,
            elapsed_sec=time.monotonic() - t_act,
        )
        steps.append(act_step)
        telemetry.record(
            "self_repair.act.success",
            factor=factor_name,
            iteration=iterations,
            series_len=len(factor_series),
        )
        if progress_callback:
            progress_callback(act_step)

        # ── DECIDE: success ──
        final_code = new_code
        is_valid = True
        last_error_kind = ReactErrorKind.NONE
        last_error_message = ""
        decide_step = ReactStep(
            state=ReactState.DECIDE,
            code=new_code,
            elapsed_sec=time.monotonic() - t_act,
        )
        steps.append(decide_step)
        telemetry.record(
            "self_repair.decide.done_success",
            factor=factor_name,
            iteration=iterations,
            series_len=len(factor_series),
        )
        if progress_callback:
            progress_callback(decide_step)
        break

    elapsed = time.monotonic() - t0
    telemetry.record(
        "self_repair.total_elapsed_sec",
        factor=factor_name,
        is_valid=is_valid,
        iterations=iterations,
        elapsed=round(elapsed, 3),
    )

    return ReactResult(
        code=final_code,
        is_valid=is_valid,
        error_kind=last_error_kind,
        error_message=last_error_message,
        iterations=iterations,
        steps=steps,
        elapsed_sec=elapsed,
    )


def _record_act_failure(
    steps: list[ReactStep],
    progress_callback: Callable[[ReactStep], None] | None,
    factor_name: str,
    iteration: int,
    kind: ReactErrorKind,
    msg: str,
    code: str,
    t_start: float,
) -> None:
    """Emit an ACT step with a failure error_kind, plus matching telemetry."""
    step = ReactStep(
        state=ReactState.ACT,
        error_kind=kind,
        error_message=msg,
        code=code,
        elapsed_sec=time.monotonic() - t_start,
    )
    steps.append(step)
    get_telemetry().record(
        f"self_repair.act.{kind.value}",
        factor=factor_name,
        iteration=iteration,
    )
    if progress_callback:
        progress_callback(step)


def _observe_and_decide(
    kind: ReactErrorKind,
    msg: str,
    messages: list[dict[str, Any]],
    steps: list[ReactStep],
    progress_callback: Callable[[ReactStep], None] | None,
    factor_name: str,
    iteration: int,
    last_code: str = "",
) -> None:
    """OBSERVE: record outcome. DECIDE: if not last round, inject error to REASON.

    Mirrors runner_v2._observe which appends the tool error as a user message
    to the conversation so the next REASON call sees it.
    """
    t = time.monotonic()
    obs_step = ReactStep(
        state=ReactState.OBSERVE,
        error_kind=kind,
        error_message=msg,
        code=last_code,
        elapsed_sec=time.monotonic() - t,
    )
    steps.append(obs_step)
    get_telemetry().record(
        "self_repair.observe",
        factor=factor_name,
        iteration=iteration,
        kind=kind.value,
    )
    if progress_callback:
        progress_callback(obs_step)

    # Truncate very long error to keep message history compact
    truncated = msg[:600] + ("...[truncated]" if len(msg) > 600 else "")
    context = ""
    if last_code:
        context = f"Your last code was:\n```python\n{last_code[:500]}\n```"
    feedback = OBSERVE_FEEDBACK_TEMPLATE.format(
        stage=kind.value,
        error=truncated,
        context=context,
    )
    messages.append({"role": "user", "content": feedback})


__all__ = [
    "ReactState",
    "ReactErrorKind",
    "ReactStep",
    "ReactResult",
    "compile_to_code_react",
]
