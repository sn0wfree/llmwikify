"""AST node types for LLM-compiled polars expressions.

Pydantic-typed AST. 157 QuantNodes operators as Literal enum (entropy -40%).
LLM emits JSON, deterministic compiler turns AST -> polars.Expr.

Reference: docs/designs/llm_compile_loop_v4.md
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# 157 QuantNodes operator names (verbatim from _OPERATOR_REGISTRY)
QN_OPS = (
    "abs add applymap arccos arcsin arctan astype book_to_market ceil clip "
    "combine cos div earnings_to_market fetch fill_null fill_null_by_strategy "
    "fill_zero fillna fix floor if_then_else isnull log log1p market_cap mul "
    "nan_to_null nanargmax nanargmin nancount nanmax nanmean nanmedian nanmin "
    "nanprod nanquantile nanstd nansum nanvar notnull pow replace sign sin "
    "sqrt square sub tan weighted_sum where "
    "correlation covariance decay_exp decay_linear delay delta diff ewm_corr "
    "ewm_cov ewm_mean ewm_std ewm_var expanding_corr expanding_count "
    "expanding_cov expanding_kurt expanding_max expanding_mean expanding_median "
    "expanding_min expanding_quantile expanding_skew expanding_std expanding_sum "
    "expanding_var lag pct_change ref regress rolling_argmax rolling_argmin "
    "rolling_change_rate rolling_corr rolling_count rolling_cov rolling_kurt "
    "rolling_max rolling_mean rolling_median rolling_min rolling_prod "
    "rolling_quantile rolling_rank rolling_skew rolling_std rolling_sum "
    "rolling_var shift ts_argmax ts_argmin ts_corr ts_cov ts_delta ts_lag "
    "ts_lead ts_max ts_mean ts_median ts_min ts_pct_change ts_prod ts_rank "
    "ts_shift ts_std ts_sum vwap zscored cross_sectional_mean "
    "cross_sectional_rank cross_sectional_std cross_sectional_sum "
    "cross_sectional_zscore fillNaNByFun fillNaNByRegress group_norm "
    "group_winsorize ic mad neutralize neutralize_market orthogonalize rank "
    "rank_ic scale standardizeRank standardizeZScore weightStandardize "
    "winsorize zscore aggr_count aggr_max aggr_mean aggr_median aggr_min "
    "aggr_prod aggr_quantile aggr_std aggr_sum aggr_var aggregate blend "
    "chg_ids disaggregate merge nav rebase"
).split()
assert len(QN_OPS) == 157, f"Expected 157 ops, got {len(QN_OPS)}"


class NodeType(str, Enum):
    """AST node op types — leaf, arithmetic, polars, QuantNodes."""

    # Leaves
    COL = "col"
    LIT = "lit"

    # Arithmetic
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    POW = "pow"
    NEG = "neg"
    ABS = "abs"
    SIGN = "sign"
    LOG = "log"
    SQRT = "sqrt"
    LT = "lt"
    GT = "gt"
    LE = "le"
    GE = "ge"
    EQ = "eq"

    # Polars native
    PL_WHEN = "pl_when"
    PL_MAX_H = "pl_max_h"
    PL_MIN_H = "pl_min_h"

    # QuantNodes (string operators — the LLM emits these names verbatim)
    @classmethod
    def _missing_(cls, value: object) -> NodeType:
        if isinstance(value, str) and value in QN_OPS:
            return str.__new__(cls, value)  # type: ignore[arg-type,return-value]
        raise ValueError(f"Unknown op: {value!r}")

    # Mark as extensible
    QN_OP = "qn_op"  # dynamic — op name in 'op' field


OpName = Literal[tuple(QN_OPS)]  # type: ignore[valid-type]


class ASTNode(BaseModel):
    """Single AST node."""

    op: str  # NodeType value OR one of QN_OPS
    args: list[ASTNode] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    value: str | float | int | bool | None = None  # for COL/LIT

    model_config = {"extra": "forbid"}


# Self-reference for forward declaration
ASTNode.model_rebuild()


def make_col(name: str) -> ASTNode:
    return ASTNode(op="col", value=name)


def make_lit(value: str | float | int | bool) -> ASTNode:
    return ASTNode(op="lit", value=value)


def make_binary(op: str, left: ASTNode, right: ASTNode) -> ASTNode:
    return ASTNode(op=op, args=[left, right])


def make_unary(op: str, operand: ASTNode) -> ASTNode:
    return ASTNode(op=op, args=[operand])


def make_call(op: str, args: list[ASTNode], **kwargs: Any) -> ASTNode:
    return ASTNode(op=op, args=args, kwargs=kwargs)


# Operator argument-count spec for validation
# (min_args, max_args, allowed_kwarg_keys or "*" for any)
OP_SPEC: dict[str, tuple[int, int, set[str] | Literal["*"]]] = {
    # Leaves
    "col": (0, 0, set()),
    "lit": (0, 0, set()),
    # Arithmetic
    "add": (2, 2, set()),
    "sub": (2, 2, set()),
    "mul": (2, 2, set()),
    "div": (2, 2, set()),
    "pow": (2, 2, set()),
    "neg": (1, 1, set()),
    "abs": (1, 1, set()),
    "sign": (1, 1, set()),
    "log": (1, 1, set()),
    "sqrt": (1, 1, set()),
    "lt": (2, 2, set()),
    "gt": (2, 2, set()),
    "le": (2, 2, set()),
    "ge": (2, 2, set()),
    "eq": (2, 2, set()),
    # Polars
    "pl_when": (1, 3, set()),  # condition, then_val, otherwise_val
    "pl_max_h": (1, 99, set()),
    "pl_min_h": (1, 99, set()),
    # Time-series rolling / ts (window required)
    "rolling_mean": (1, 1, {"window"}),
    "rolling_std": (1, 1, {"window"}),
    "rolling_sum": (1, 1, {"window"}),
    "rolling_max": (1, 1, {"window"}),
    "rolling_min": (1, 1, {"window"}),
    "rolling_corr": (2, 2, {"window"}),
    "rolling_cov": (2, 2, {"window"}),
    "rolling_argmax": (1, 1, {"window"}),
    "rolling_argmin": (1, 1, {"window"}),
    "rolling_rank": (1, 1, {"window"}),
    "rolling_skew": (1, 1, {"window"}),
    "rolling_kurt": (1, 1, {"window"}),
    "rolling_count": (1, 1, {"window"}),
    "rolling_quantile": (1, 1, {"window"}),
    "rolling_median": (1, 1, {"window"}),
    "rolling_prod": (1, 1, {"window"}),
    "rolling_var": (1, 1, {"window"}),
    "rolling_change_rate": (1, 1, {"window"}),
    "ts_argmax": (1, 1, {"window"}),
    "ts_argmin": (1, 1, {"window"}),
    "ts_rank": (1, 1, {"window"}),
    "ts_mean": (1, 1, {"window"}),
    "ts_std": (1, 1, {"window"}),
    "ts_sum": (1, 1, {"window"}),
    "ts_quantile": (1, 1, {"window"}),
    "ts_delta": (1, 1, {"window"}),
    "ts_diff": (1, 1, {"window"}),
    "ts_lag": (1, 1, {"window"}),
    "ts_pct_change": (1, 1, {"window"}),
    # Correlation / covariance (covered below in section)
    "ts_corr": (2, 2, {"window"}),
    "ts_cov": (2, 2, {"window"}),
    # Time-series (no window required, periods kwarg)
    "delta": (1, 1, {"periods"}),
    "delay": (1, 1, {"periods"}),
    "diff": (1, 1, {"periods"}),
    "lag": (1, 1, {"periods"}),
    "shift": (1, 1, {"periods"}),
    "pct_change": (1, 1, {"periods"}),
    "ref": (1, 1, {"periods"}),
    "decay_linear": (1, 1, {"window"}),
    "decay_exp": (1, 1, {"window"}),
    "ewm_mean": (1, 1, {"span"}),
    "ewm_std": (1, 1, {"span"}),
    "ewm_var": (1, 1, {"span"}),
    "ewm_corr": (2, 2, {"span"}),
    "ewm_cov": (2, 2, {"span"}),
    # Cross-sectional / section
    "rank": (1, 1, set()),
    "scale": (1, 1, set()),
    "zscore": (1, 1, set()),
    "winsorize": (1, 1, set()),
    "neutralize": (1, 1, set()),
    "indneutralize": (1, 1, set()),
    # Correlation / covariance (2-arg with window)
    "correlation": (2, 2, {"window"}),
    "covariance": (2, 2, {"window"}),
    # Point-wise
    "where": (3, 3, set()),
    "if_then_else": (3, 3, set()),
    "log1p": (1, 1, set()),
    "square": (1, 1, set()),
    "clip": (1, 1, set()),
    "ceil": (1, 1, set()),
    "floor": (1, 1, set()),
    "fix": (1, 1, set()),
    "fill_null": (1, 1, set()),
    "fill_null_by_strategy": (1, 1, set()),
    "fill_zero": (1, 1, set()),
    "fillna": (1, 1, set()),
    "nan_to_null": (1, 1, set()),
    "isnull": (1, 1, set()),
    "notnull": (1, 1, set()),
    "replace": (1, 1, set()),
    "astype": (1, 1, set()),
    "applymap": (1, 1, set()),
    "fetch": (0, 0, set()),
    "weighted_sum": (2, 99, set()),
    "combine": (2, 2, set()),
    "market_cap": (0, 0, set()),
    "book_to_market": (0, 0, set()),
    "earnings_to_market": (0, 0, set()),
    "regress": (2, 2, set()),
    # Math
    "arccos": (1, 1, set()),
    "arcsin": (1, 1, set()),
    "arctan": (1, 1, set()),
    "cos": (1, 1, set()),
    "sin": (1, 1, set()),
    "tan": (1, 1, set()),
    # NaN-aware aggregations (used in rolling/expanding context)
    "nanmean": (1, 1, set()),
    "nanstd": (1, 1, set()),
    "nansum": (1, 1, set()),
    "nanvar": (1, 1, set()),
    "nanmax": (1, 1, set()),
    "nanmin": (1, 1, set()),
    "nanmedian": (1, 1, set()),
    "nanprod": (1, 1, set()),
    "nanargmax": (1, 1, set()),
    "nanargmin": (1, 1, set()),
    "nancount": (1, 1, set()),
    "nanquantile": (1, 1, set()),
    "argmax": (1, 1, set()),
    "argmin": (1, 1, set()),
    "count": (1, 1, set()),
    "max": (1, 1, set()),
    "mean": (1, 1, set()),
    "median": (1, 1, set()),
    "min": (1, 1, set()),
    "prod": (1, 1, set()),
    "quantile": (1, 1, set()),
    "skew": (1, 1, set()),
    "std": (1, 1, set()),
    "sum": (1, 1, set()),
    "var": (1, 1, set()),
    "mad": (1, 1, set()),
}


def is_known_op(op: str) -> bool:
    """Check if op is a valid node type or QuantNodes operator."""
    try:
        NodeType(op)
        return True
    except ValueError:
        return op in QN_OPS


def get_op_spec(op: str) -> tuple[int, int, set[str] | Literal["*"]]:
    """Get (min_args, max_args, allowed_kwarg_keys) for an op."""
    if op in OP_SPEC:
        return OP_SPEC[op]
    if op in QN_OPS:
        return (1, 99, "*")
    raise ValueError(f"Unknown op: {op!r}")


__all__ = [
    "ASTNode",
    "NodeType",
    "QN_OPS",
    "OpName",
    "make_col",
    "make_lit",
    "make_binary",
    "make_unary",
    "make_call",
    "is_known_op",
    "get_op_spec",
    "OP_SPEC",
]
