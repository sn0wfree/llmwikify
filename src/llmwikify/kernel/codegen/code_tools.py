"""code_extract — Python code extraction and syntax validation.

Pure building blocks: no polars / QuantNodes / factor execution.

Functions:
  - extract_python(text) → str | None
        Look for ```python ... ``` fenced block, fall back to raw text.
  - validate_syntax(code) → (is_valid: bool, error: str)
        ast.parse check.
"""

from __future__ import annotations

import ast
import re

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
