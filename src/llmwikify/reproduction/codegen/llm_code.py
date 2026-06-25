"""Shared codegen utilities for factor code generation pipeline.

Extracted from test_one_factor_llm_code.py, factor_compiler_react.py,
and factor_extractor.py to eliminate ~265 lines of duplication.

Usage:
    from llmwikify.reproduction.codegen_utils import (
        SYSTEM_PROMPT_CODE,
        build_llm_client,
        extract_python,
        validate_syntax,
        validate_safety,
        execute_code,
        extract_json_from_response,
        generate_factor_code,
    )
"""
from __future__ import annotations

import ast
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


# ─── SYSTEM_PROMPT_CODE ────────────────────────────────────────────

SYSTEM_PROMPT_CODE = """You are a quant factor code generator.

Translate a factor formula into a Python function `compute_factor(df)` that returns a polars Series
of factor values, one per row of `df`.

## #1 FAILURE CAUSE: PYTHON BOOLEAN ON POLARS EXPRESSION
YOUR CODE WILL CRASH with "truth value of an Expr is ambiguous" if you do this.

NEVER use `if`/`elif`/`else`, `and`, `or`, `not` with polars expressions
or QuantNodes operators (rank, correlation, neutralize, rolling_*, ts_*, etc).

❌ WRONG (all crash):
  if rank(pl.col('x')) > 0:
  if correlation(a, b) > 0.5:
  if neutralize(vwap, industry) > threshold and volume > 0:
  if IndNeutralize(close, industry) > 0 and rank(pl.col('volume')) > 0.5:

✓ RIGHT:
  factor = pl.when(rank(pl.col('x')) > 0).then(-1).otherwise(0)
  factor = pl.when(correlation(a, b) > 0.5).then(1).otherwise(0)
  factor = pl.when(neutralize(vwap, industry) > 0).then(volume).otherwise(0)
  factor = pl.when(IndNeutralize(close, industry) > 0 & rank(pl.col('volume')) > 0.5).then(1).otherwise(0)

Also: use `&` (not `and`), `|` (not `or`), `~` (not `not`).

## RULE 2: USE FUNCTION FORM
QuantNodes operators are FUNCTIONS, NOT Expr methods.
  ✓ `rolling_std(pl.col('returns'), window=20)`
  ✗ `pl.col('returns').rolling_std(window=20)`

## RULE 3: MATERIALIZE BEFORE .over('date')
When rank/scale depends on a rolling/correlation result, store it first:
  ✓ `df = df.with_columns(correlation(a, b, window=200).alias('_ts'))`
    `factor = rank(pl.col('_ts')).over('date')`
  ✗ `rank(correlation(a, b, window=200)).over('date')`  ← re-evaluates in 50-row group → NaN

## DO NOT
- DO NOT call `df.sort(...)` — data is already sorted

## DATA
`df` is a polars DataFrame (long format: rows = (date, code) pairs).
Columns: date, code, close, open, high, low, volume, returns, vwap, industry.

## OPERATORS

### QuantNodes time-series (kwargs={"window": N})
  rolling_mean, rolling_std, rolling_sum, rolling_max, rolling_min,
  rolling_corr (2 args), rolling_cov (2 args), rolling_argmax, rolling_argmin,
  ts_argmax, ts_argmin, ts_rank, ts_mean, ts_std, ts_min, ts_max, ts_sum, ts_quantile,
  ts_delta, ts_diff, ts_lag, ts_pct_change, ts_corr (2), ts_cov (2)
  decay_linear, decay_exp, correlation (2), covariance (2)

### QuantNodes (require periods kwarg)
  delta, diff, lag, delay, shift, pct_change, ref

### Cross-sectional (require .over('date'))
  rank, scale, zscore, winsorize, neutralize
  -> neutralize(f, group=pl.col('industry')): industry neutralization

### Polars native
  pl.when(cond).then(x).otherwise(y), pl.col('x').abs(), .sign(), .log(), .sqrt()

## OUTPUT FORMAT

```python
def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Rule 3: materialize rolling result first
    df = df.with_columns(rolling_std(pl.col('returns'), window=20).alias('_std'))
    # Rule 1: use pl.when, not if
    inner = pl.when(pl.col('returns') < 0).then(pl.col('_std')).otherwise(pl.col('close'))
    # Rule 3: materialize ts_argmax
    df = df.with_columns(ts_argmax(inner.sign() * (inner.abs() ** 2), window=5).alias('_argmax'))
    # Rule 3+2: rank on materialized column, function form
    factor = rank(pl.col('_argmax')).over('date') - 0.5
    return df.select(factor).to_series()
```

CRITICAL: Return `pl.Series` with same length as `df`. Output ONLY code block.
"""


# ─── Compiled regex ────────────────────────────────────────────────

_PYTHON_FENCE_RE = re.compile(r"```python\s*\n(.+?)\n```", re.DOTALL)


# ─── LLM client ───────────────────────────────────────────────────

def build_llm_client(model: str | None = None) -> Any:
    """Build StreamableLLMClient from ~/.llmwikify/llmwikify.json.

    Thin wrapper around llm_extraction.llm_factory.build_default_client().
    Centralizes client creation so callers don't parse config manually.

    Args:
        model: Override model name (default: config's model field).

    Returns:
        Configured StreamableLLMClient instance.

    Raises:
        RuntimeError: If config missing, disabled, or required fields absent.
    """
    from ..common.llm_factory import build_default_client
    return build_default_client(model=model)


# ─── Code extraction ───────────────────────────────────────────────

def extract_python(text: str) -> str | None:
    """Extract Python code from LLM response.

    Looks for ```python ... ``` fenced block first.
    Falls back to finding `def compute_factor` in raw text.

    Args:
        text: Raw LLM response text.

    Returns:
        Extracted code string, or None if nothing found.
    """
    if not text:
        return None
    m = _PYTHON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    if "def compute_factor" in text:
        idx = text.index("def compute_factor")
        return text[idx:].strip()
    return None


# ─── Syntax validation ────────────────────────────────────────────

def validate_syntax(code: str) -> tuple[bool, str]:
    """Check Python syntax via ast.parse.

    Args:
        code: Python source code string.

    Returns:
        (is_valid, error_message) where error_message is empty on success.
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as exc:
        return False, f"line {exc.lineno}: {exc.msg}"


# ─── Safety validation ────────────────────────────────────────────

def validate_safety(code: str) -> tuple[bool, str]:
    """Delegate to CodeSandbox.validate for safety check.

    Args:
        code: Python source code string.

    Returns:
        (is_safe, error_message) where error_message is empty on success.
    """
    from QuantNodes.ai.sandbox import CodeSandbox

    sandbox = CodeSandbox(max_code_length=500_000)
    validation = sandbox.validate(code)
    if not validation.is_safe:
        return False, "; ".join(str(e) for e in validation.errors)
    return True, ""


# ─── Code execution ────────────────────────────────────────────────

def build_execute_namespace() -> dict[str, Any]:
    """Build namespace dict with QuantNodes operators + polars/pandas/numpy.

    Returns:
        Dict mapping operator names to functions, plus pl/pd/np.
    """
    from QuantNodes.operators.proxy import get_operator, list_operators

    ns: dict[str, Any] = {
        "pl": pl,
        "polars": pl,
        "pd": __import__("pandas"),
        "np": __import__("numpy"),
    }
    for op_name in list_operators():
        op_func = get_operator(op_name)
        if op_func is not None:
            ns[op_name] = op_func
    return ns


def execute_code(
    code: str,
    df: pl.DataFrame,
    timeout_sec: float = 120.0,
) -> pl.Series:
    """Execute LLM-generated compute_factor(code) via CodeSandbox.

    Builds namespace with QuantNodes operators, wraps code to auto-call
    compute_factor(df), validates safety, executes with timeout.

    Args:
        code: Python source defining compute_factor(df) -> pl.Series.
        df: Polars DataFrame passed as `df` to compute_factor.
        timeout_sec: Execution timeout in seconds (default 120).

    Returns:
        pl.Series of factor values aligned with df's row order.

    Raises:
        ValueError: If code is unsafe, compute_factor not found, or
            result is not a Series.
        TimeoutError: If execution exceeds timeout_sec.
    """
    from QuantNodes.ai.sandbox import CodeSandbox

    namespace = build_execute_namespace()
    namespace["df"] = df

    sandbox = CodeSandbox(max_code_length=500_000)
    if not sandbox.validate(code).is_safe:
        raise ValueError("Unsafe code (sandbox rejected)")

    # Wrap: define compute_factor, then call it and capture the result.
    wrapped = code.rstrip() + "\n_factor_result = compute_factor(df)\n"

    result_box = [None]
    error_box = [None]

    def _run():
        try:
            result_box[0] = sandbox.validate_and_execute(wrapped, namespace)
        except Exception as exc:
            error_box[0] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise TimeoutError(f"compute_factor() exceeded {timeout_sec}s timeout")
    if error_box[0] is not None:
        raise error_box[0]
    result = result_box[0]
    series = result.get("_factor_result")
    if series is None:
        # Search the namespace for any pl.Series
        for v in result.values():
            if isinstance(v, pl.Series):
                series = v
                break
    if series is None:
        raise ValueError(
            f"compute_factor() did not return a Series; got keys: {list(result.keys())}"
        )
    if callable(series):
        raise ValueError("compute_factor is a function, not a Series (never called)")
    if isinstance(series, pl.Expr):
        # LLM returned a polars Expr; evaluate it on the dataframe
        series = df.select(series.alias("__factor__")).to_series()
    if not isinstance(series, pl.Series):
        series = pl.Series(series)
    return series


# ─── JSON extraction ───────────────────────────────────────────────

def extract_json_from_response(text: str) -> dict | None:
    """Parse JSON from ```json ... ``` fenced block in LLM response.

    Tolerant: if no fence, tries to find JSON object `{...}` in text.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("[codegen_utils] fenced JSON parse failed: %s", exc)

    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("[codegen_utils] raw JSON parse failed: %s", exc)

    return None


# ─── High-level convenience ────────────────────────────────────────

def generate_factor_code(
    factor_name: str,
    formula_brief: str,
    df: pl.DataFrame,
    *,
    llm: Any | None = None,
    system_prompt: str | None = None,
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
    model: str | None = None,
    progress_callback: Any | None = None,
    prompts: Any | None = None,
) -> tuple[str | None, pl.Series | None, str | None, dict]:
    """High-level convenience: build client (if needed) + run ReAct loop.

    Combines build_llm_client + compile_to_code_react into a single call.
    Returns (code, factor_series, error, react_result_dict).

    Args:
        factor_name: Display name (e.g. "alpha-001").
        formula_brief: Natural-language formula description.
        df: Polars DataFrame in long format.
        llm: Pre-built LLM client (if None, calls build_llm_client(model)).
        system_prompt: System prompt (if None, uses SYSTEM_PROMPT_CODE or prompts).
        max_repair_rounds: Max self-repair iterations (default 3).
        temperature: LLM temperature (default 0.3).
        model: Override model name (only used if llm is None).
        progress_callback: Optional hook invoked after each ReactStep.
        prompts: Optional PromptRegistry. When provided and system_prompt is None,
                 looks up "code_gen" prompt from registry.

    Returns:
        (code, factor_series, error_message, react_result_dict)
        where code/series are None on failure, error is None on success.
    """
    from .react_engine import compile_to_code_react

    if llm is None:
        llm = build_llm_client(model=model)
    if system_prompt is None:
        if prompts is not None:
            try:
                group = prompts.get("code_gen", version="latest")
                system_prompt = group.system
            except (KeyError, AttributeError):
                system_prompt = SYSTEM_PROMPT_CODE
        else:
            system_prompt = SYSTEM_PROMPT_CODE

    result = compile_to_code_react(
        factor_name=factor_name,
        formula_brief=formula_brief,
        system_prompt=system_prompt,
        df=df,
        llm=llm,
        max_repair_rounds=max_repair_rounds,
        temperature=temperature,
        progress_callback=progress_callback,
    )

    if not result.is_valid:
        return None, None, result.error_message, result.to_dict()

    # Re-execute the final code to get the Series (compile_to_code_react
    # validates but doesn't return the Series)
    try:
        series = execute_code(result.code, df)
    except Exception as exc:
        return None, None, f"final execute failed: {exc}", result.to_dict()
    return result.code, series, None, result.to_dict()


__all__ = [
    "SYSTEM_PROMPT_CODE",
    "build_llm_client",
    "extract_python",
    "validate_syntax",
    "validate_safety",
    "build_execute_namespace",
    "execute_code",
    "extract_json_from_response",
    "generate_factor_code",
]
