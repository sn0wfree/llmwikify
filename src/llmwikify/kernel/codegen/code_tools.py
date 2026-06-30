"""code_extract — Python code extraction, validation, and execution.

C1: extracted from `reproduction/codegen/llm_code.py`. Pure building blocks
that depend only on `polars` + `QuantNodes` (third-party).

Functions:
  - extract_python(text) → str | None
        Look for ```python ... ``` fenced block, fall back to raw text.
  - validate_syntax(code) → (is_valid: bool, error: str)
        ast.parse check.
  - validate_safety(code) → (is_safe: bool, error: str)
        CodeSandbox.validate safety check.
  - build_execute_namespace() → dict[str, Any]
        Namespace with QuantNodes operators + polars/pandas/numpy.
  - execute_code(code, df, timeout_sec) → pl.Series
        Run compute_factor(df) via CodeSandbox with timeout.
"""
from __future__ import annotations

import ast
import re
import threading
from typing import Any

import polars as pl

# ─── Compiled regex ────────────────────────────────────────────────

_PYTHON_FENCE_RE = re.compile(r"```python\s*\n(.+?)\n```", re.DOTALL)


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
