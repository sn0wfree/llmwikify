"""Code generation stage: LLM produces factor code."""
from __future__ import annotations

from typing import Any

import polars as pl

from llmwikify.reproduction.codegen.llm_code import (
    SYSTEM_PROMPT_CODE,
    execute_code,
    extract_python,
    validate_safety,
    validate_syntax,
)

from .base import Stage, StageContext


class CodegenStage(Stage):
    name = "codegen"
    required_prompts = ["code_gen"]

    def execute(self, ctx: StageContext) -> StageContext:
        # Stub: will be wired in Phase 14F
        return ctx


def llm_code_oneshot(
    factor_name: str,
    formula_brief: str,
    df_pl: pl.DataFrame,
    llm: Any,
    temperature: float = 0.3,
) -> tuple[str | None, pl.Series | None, str | None, int]:
    """Old 1-shot path: single LLM call → extract → validate → execute.

    Returns (code, factor_series, error, stage_idx) where stage_idx maps to
    "llm" / "extract" / "syntax" / "safety" / "execute" / None on success.
    Used by `--no-react` mode.

    Moved from scripts/test_one_factor_llm_code.py:172 to here so it can be
    reused by run_101_alphas.py's `use_react=False` branch (which was
    previously broken with NameError).
    """
    user_prompt = f"""Factor: {factor_name}
Formula (pseudo-code): {formula_brief}

Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series` that computes
this factor. Use QuantNodes operators (rank, ts_argmax, rolling_std, etc.) which are
in the namespace, and use polars expressions otherwise.

Output ONLY the code block."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CODE},
        {"role": "user", "content": user_prompt},
    ]
    try:
        content = llm.chat(messages=messages, temperature=temperature)
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}", -1

    print(f"\n[LLM] raw response ({len(content)} chars):")
    print(content[:500] + ("..." if len(content) > 500 else ""))

    code = extract_python(content)
    if not code:
        return None, None, "no code fence", 0
    print(f"\n[extract] code ({len(code)} chars):")
    print(code)

    syntax_ok, syntax_err = validate_syntax(code)
    if not syntax_ok:
        return None, None, syntax_err, 1
    print("[syntax] OK")

    safe_ok, safe_err = validate_safety(code)
    if not safe_ok:
        return None, None, safe_err, 2
    print("[safety] OK")

    try:
        series = execute_code(code, df_pl)
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}", 3
    print(f"[execute] OK: factor_series len={len(series)}, dtype={series.dtype}")
    print(f"[execute] sample: {series.head(5).to_list()}")
    return code, series, None, None
