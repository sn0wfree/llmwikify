"""Error categorizer — convert raw exceptions into structured {kind, ...} errors.

Reference: docs/designs/llm_compile_loop_v4.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StructuredError:
    """Structured compile/extract error."""

    kind: str
    message: str
    suggestion: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Format for re-prompting LLM with category + suggestion."""
        lines = [f"[{self.kind}] {self.message}"]
        if self.suggestion:
            lines.append(f"Suggestion: {self.suggestion}")
        return "\n".join(lines)


def categorize_compile_error(
    error: Exception,
    available_columns: list[str] | None = None,
) -> StructuredError:
    """Categorize a CompileError or other compile-time exception."""
    err_str = str(error)
    err_lower = err_str.lower()

    if "unknownop" in err_lower or "not in 157 known operators" in err_lower:
        # Extract op name if possible
        m = re.search(r"'([^']+)'", err_str)
        op = m.group(1) if m else "?"
        return StructuredError(
            kind="UnknownOp",
            message=f"Operator {op!r} is not in the 157 known operators",
            suggestion=(
                "Use only operators from the provided list (rolling_mean, ts_argmax, "
                "rank, scale, correlation, etc.). Do NOT invent new names like "
                "log_diff (use diff(log(x)) instead), pl.when(cond, t, o) "
                "(use pl.when(cond).then(t).otherwise(o) instead)."
            ),
            context={"op": op},
        )

    if "wrongargcount" in err_lower or "expects" in err_lower and "args" in err_lower:
        return StructuredError(
            kind="WrongArgCount",
            message=err_str,
            suggestion=(
                "Check operator arity. unary ops need 1 arg (e.g. abs, log); "
                "binary need 2 (e.g. add, sub); rolling/ts need 1 child + window kwarg; "
                "correlation needs 2 children + window kwarg."
            ),
        )

    if "missingkwarg" in err_lower or "requires kwargs" in err_lower:
        return StructuredError(
            kind="MissingKwarg",
            message=err_str,
            suggestion=(
                "rolling_mean/std/sum/max/min/corr need kwargs={'window': N}. "
                "delta/diff/shift/lag need kwargs={'periods': N}. "
                "ewm_mean/std need kwargs={'span': N}."
            ),
        )

    if "unknownkwarg" in err_lower or "unexpected kwargs" in err_lower:
        return StructuredError(
            kind="UnknownKwarg",
            message=err_str,
            suggestion="Only use window/periods/span kwargs. Remove all others.",
        )

    if "typemismatch" in err_lower:
        return StructuredError(
            kind="TypeMismatch",
            message=err_str,
            suggestion="col.value must be string column name; lit.value must be number/string/bool.",
        )

    if "unknowncolumn" in err_lower or "could not find column" in err_lower:
        col = re.search(r"'([^']+)'", err_str)
        col_name = col.group(1) if col else "?"
        candidates = available_columns or []
        return StructuredError(
            kind="UnknownColumn",
            message=f"Column {col_name!r} not found in schema",
            suggestion=(
                f"Use one of: {', '.join(candidates[:8])}... "
                "(full list in SYSTEM_PROMPT)"
            ),
            context={"column": col_name, "candidates": candidates},
        )

    if "qncallfailed" in err_lower:
        return StructuredError(
            kind="QNCallFailed",
            message=err_str,
            suggestion="Check operator signature and kwarg types.",
        )

    # Fallback
    return StructuredError(
        kind="Other",
        message=err_str[:200],
        suggestion="Re-read SYSTEM_PROMPT and try again with the correct AST format.",
    )


def categorize_extract_error(
    error: Exception,
    raw_text: str = "",
) -> StructuredError:
    """Categorize AST extraction error (LLM didn't return valid JSON)."""
    err_str = str(error)

    if "json" in err_str.lower() or "jsondecode" in err_str.lower():
        return StructuredError(
            kind="InvalidJSON",
            message="LLM output is not valid JSON",
            suggestion=(
                "Output the AST as a JSON object ONLY. "
                "Use ```json { ... } ``` fence. "
                "Do NOT include prose before/after the JSON."
            ),
            context={"raw_preview": raw_text[:200]},
        )

    if "validation" in err_str.lower():
        return StructuredError(
            kind="SchemaValidation",
            message="JSON parsed but failed ASTNode validation",
            suggestion=(
                "Each node must have 'op' (string), 'args' (list of nodes), "
                "'kwargs' (dict), 'value' (string/number/bool/null). "
                "Use 'op' names from the 157 list."
            ),
            context={"raw_preview": raw_text[:200]},
        )

    return StructuredError(
        kind="Other",
        message=err_str[:200],
        suggestion="Re-read AST format example in SYSTEM_PROMPT.",
    )


__all__ = ["StructuredError", "categorize_compile_error", "categorize_extract_error"]
