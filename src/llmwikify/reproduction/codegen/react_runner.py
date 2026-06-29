"""ReAct-based LLM code generation runner.

Public API:
  - ReActProgressHook: UnifiedHook subclass that prints ReAct iteration progress
  - llm_code_react: top-level function that runs ReAct self-retry codegen

L1 extraction from scripts/run_101_alphas_v2.py (PR8). Decoupled from
RunConfig — accepts max_repair_rounds + temperature as kwargs.

Usage:
    from llmwikify.reproduction.codegen.react_runner import llm_code_react
    code, factor_series, error, react_meta = llm_code_react(
        factor_name, formula_brief, df_pl, llm,
        max_repair_rounds=3, temperature=0.3,
    )
"""
from __future__ import annotations

import logging
from typing import Any

import polars as pl

from llmwikify.apps.chat.agent.unified.core import UnifiedHook

logger = logging.getLogger(__name__)


class ReActProgressHook(UnifiedHook):
    """Unified hook: prints ReAct iteration progress to logger."""

    def on_reason_start(self, ctx: Any) -> None:
        logger.info("[REASON] iteration %s...", ctx.iteration)

    def on_act_end(self, ctx: Any, result: Any) -> None:
        if hasattr(result, "success") and result.success:
            logger.info("[ACT] OK (%s)", getattr(result, "error_kind", "none"))
        else:
            ek = getattr(result, "error_kind", "unknown")
            em = (getattr(result, "error", "") or "")[:120]
            logger.info("[ACT] %s: %s", ek, em)


def llm_code_react(
    factor_name: str,
    formula_brief: str,
    df_pl: pl.DataFrame,
    llm: Any,
    *,
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
) -> tuple[str | None, pl.Series | None, str | None, dict]:
    """ReAct self-retry code generation (public, reusable, no RunConfig dep).

    Args:
        factor_name: Factor name (e.g. "alpha-001" / "板块轮动周期表").
        formula_brief: Math description / formula expression (LLM input).
        df_pl: Long-format polars DataFrame (date, code, ...).
        llm: LLM client (any object with .chat() method).
        max_repair_rounds: Max ReAct repair attempts (default 3).
        temperature: LLM sampling temperature (default 0.3).

    Returns:
        (code, factor_series, error, react_meta):
          - code: Generated code (None on failure)
          - factor_series: Computed factor series (None on failure)
          - error: Error message (None on success)
          - react_meta: UnifiedResult.to_dict() (iterations / stop_reason)
    """
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import (
        generate_factor_code_sync,
    )

    result = generate_factor_code_sync(
        factor_name=factor_name,
        formula_brief=formula_brief,
        df=df_pl,
        llm_client=llm,
        max_repair_rounds=max_repair_rounds,
        temperature=temperature,
        hook=ReActProgressHook(),
    )

    logger.info(
        "[Unified] iterations=%s, stop_reason=%s, error=%s",
        result.iterations, result.stop_reason, result.error,
    )

    if result.error:
        return None, None, result.error, result.to_dict()
    return result.code, result.factor_series, None, result.to_dict()
