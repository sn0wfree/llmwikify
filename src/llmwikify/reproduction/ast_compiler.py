"""AST -> polars.Expr deterministic compiler.

No LLM here. Pydantic AST -> pl.Expr via dispatch table.

Reference: docs/designs/llm_compile_loop_v4.md
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import polars as pl

from .ast_nodes import ASTNode, get_op_spec, is_known_op


class CompileError(Exception):
    """Structured compile error with category, message, and suggestions."""

    def __init__(self, kind: str, message: str, **context: Any) -> None:
        self.kind = kind
        self.message = message
        self.context = context
        super().__init__(f"{kind}: {message}")


# Dispatch tables
_LEAF_FNS: dict[str, Callable[[ASTNode], pl.Expr]] = {}

_ARITH_FNS: dict[str, Callable[[list[pl.Expr]], pl.Expr]] = {
    "add": lambda c: c[0] + c[1],
    "sub": lambda c: c[0] - c[1],
    "mul": lambda c: c[0] * c[1],
    "div": lambda c: c[0] / c[1],
    "pow": lambda c: c[0] ** c[1],
    "neg": lambda c: -c[0],
    "abs": lambda c: c[0].abs(),
    "sign": lambda c: c[0].sign(),
    "log": lambda c: c[0].log(),
    "sqrt": lambda c: c[0].sqrt(),
    "lt": lambda c: c[0] < c[1],
    "gt": lambda c: c[0] > c[1],
    "le": lambda c: c[0] <= c[1],
    "ge": lambda c: c[0] >= c[1],
    "eq": lambda c: c[0] == c[1],
}

_POLARS_FNS: dict[str, Callable[[ASTNode, list[pl.Expr]], pl.Expr]] = {
    "pl_when": lambda n, c: (
        pl.when(c[0]) if len(c) == 1
        else pl.when(c[0]).then(c[1]).otherwise(c[2])
    ),
    "pl_max_h": lambda n, c: pl.max_horizontal(*c),
    "pl_min_h": lambda n, c: pl.min_horizontal(*c),
    # PR-3 (2026-06-21): 6 new polars native operators
    "pl_concat_list": lambda n, c: pl.concat_list(c),
    "pl_str_contains": lambda n, c: c[0].str.contains(n.kwargs["pattern"]),
    "pl_str_length": lambda n, c: c[0].str.len_chars(),
    "pl_dt_year": lambda n, c: c[0].dt.year(),
    "pl_dt_month": lambda n, c: c[0].dt.month(),
    "pl_dt_day": lambda n, c: c[0].dt.day(),
    "pl_alias": lambda n, c: c[0].alias(n.kwargs["name"]),
    "pl_fill_null": lambda n, c: c[0].fill_null(n.kwargs["value"]),
}


def _compile_leaf(node: ASTNode) -> pl.Expr:
    """Compile leaf node (COL/LIT)."""
    if node.op == "col":
        if not isinstance(node.value, str):
            raise CompileError(
                "TypeMismatch", "col.value must be string",
                op=node.op, got=type(node.value).__name__,
            )
        return pl.col(node.value)
    if node.op == "lit":
        if node.value is None:
            raise CompileError("TypeMismatch", "lit.value cannot be None", op=node.op)
        return pl.lit(node.value)
    raise CompileError("UnknownOp", f"Leaf op not supported: {node.op!r}")


def _compile_qn_call(
    node: ASTNode, children: list[pl.Expr], op_func: Callable[..., pl.Expr]
) -> pl.Expr:
    """Compile a QuantNodes call (positional children + kwargs)."""
    if "window" in node.kwargs:
        return op_func(*children, window=node.kwargs["window"])
    if "periods" in node.kwargs:
        return op_func(*children, periods=node.kwargs["periods"])
    if "span" in node.kwargs:
        return op_func(*children, span=node.kwargs["span"])
    return op_func(*children, **node.kwargs)


def _resolve_qn_op(op: str) -> Callable[..., pl.Expr]:
    """Look up a QuantNodes operator function by name.

    PR-1 (2026-06-21): use public API get_operator (not the private registry).
    Returns the function itself (None if not found).
    """
    from QuantNodes.operators.proxy import get_operator
    op_func = get_operator(op)
    if op_func is None:
        raise CompileError(
            "UnknownOp", f"QN op {op!r} not found in registry", op=op,
        )
    return op_func


def _resolve_semantic_op(op: str, kwargs: dict[str, Any]):
    """PR-5 (2026-06-21): Resolve a semantic op to its AST template.

    Returns None if op is not a registered semantic op.
    """
    from .semantic_registry import get_op

    if get_op(op) is None:
        return None
    from .semantic_registry import instantiate
    return instantiate(op, kwargs)


def compile_ast(node: ASTNode) -> pl.Expr:
    """Recursively compile an AST node into a polars expression.

    Raises CompileError on:
    - UnknownOp
    - WrongArgCount
    - TypeMismatch
    - MissingKwarg
    - QNCallFailed
    """
    if not is_known_op(node.op):
        # PR-5 (2026-06-21): try semantic registry (Layer 4)
        sem_ast = _resolve_semantic_op(node.op, node.kwargs)
        if sem_ast is not None:
            return compile_ast(sem_ast)
        raise CompileError(
            "UnknownOp", f"Op not in 157 known operators: {node.op!r}", op=node.op,
        )

    if node.op in ("col", "lit"):
        return _compile_leaf(node)

    min_args, max_args, allowed_kwargs = get_op_spec(node.op)
    if not (min_args <= len(node.args) <= max_args):
        raise CompileError(
            "WrongArgCount",
            f"Op {node.op!r} expects {min_args}-{max_args} args, got {len(node.args)}",
            op=node.op, expected_min=min_args, expected_max=max_args, got=len(node.args),
        )

    if allowed_kwargs != "*" and node.kwargs:
        bad_kwargs = set(node.kwargs.keys()) - allowed_kwargs
        if bad_kwargs:
            raise CompileError(
                "UnknownKwarg",
                f"Op {node.op!r} got unexpected kwargs {bad_kwargs}",
                op=node.op, bad_kwargs=list(bad_kwargs), allowed=list(allowed_kwargs),
            )

    children: list[pl.Expr] = [compile_ast(c) for c in node.args]

    if node.op in _ARITH_FNS:
        return _ARITH_FNS[node.op](children)

    if node.op in _POLARS_FNS:
        return _POLARS_FNS[node.op](node, children)

    op_func = _resolve_qn_op(node.op)

    if allowed_kwargs and allowed_kwargs != "*":
        missing = allowed_kwargs - set(node.kwargs.keys())
        if missing:
            raise CompileError(
                "MissingKwarg",
                f"Op {node.op!r} requires kwargs {allowed_kwargs}, missing {missing}",
                op=node.op, missing=list(missing),
            )

    try:
        return _compile_qn_call(node, children, op_func)
    except Exception as exc:
        raise CompileError(
            "QNCallFailed",
            f"QN op {node.op!r} call failed: {exc}",
            op=node.op, args_count=len(children), kwargs=node.kwargs,
        ) from exc


__all__ = ["compile_ast", "CompileError"]
