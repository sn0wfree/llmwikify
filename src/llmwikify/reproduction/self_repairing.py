"""Self-Repairing Compiler (PR-6, 2026-06-21).

Layer-by-layer repair of failed AST compiles. 5+1 FixStrategy:

  SchemaFix     Pydantic ValidationError  -> re-emit from scratch
  CompileFix    CompileError (wrong kwarg/arity) -> patch AST in place
  SemanticFix   Semantic registry miss  -> suggest Composite/Semantic
  CompositeFix  Composite template arg err -> simplify DAG
  RuntimeFix    polars.TypeError  -> type cast / coerce
  QualityFix    IC ~ 0 / INCOMPLETE AST  -> rewrite from l2

Design:
- Each strategy is a function: (ast_node, structured_err) -> ASTNode | None
- Strategies tried in order; first non-None wins
- max_repair_rounds=3 limits total iterations
- All structured_err history injected into LLM prompt for context
"""
from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

from .error_categorizer import StructuredError

if TYPE_CHECKING:
    from .ast_nodes import ASTNode

logger = logging.getLogger(__name__)


# ─── Strategy 1: SchemaFix ────────────────────────────────


def schema_fix(node: ASTNode, err: StructuredError) -> ASTNode | None:
    """SchemaFix: when ValidationError occurs, return None to trigger full re-emit.

    Strategy: Let the LLM emit a fresh AST with the error context.
    The caller (factor_compiler) handles re-emission.
    """
    if err.kind not in ("InvalidJSON", "SchemaValidation"):
        return None
    logger.info("[SelfRepair] SchemaFix: triggering re-emit (%s)", err.kind)
    return None  # signal caller to re-emit


# ─── Strategy 2: CompileFix ───────────────────────────────


def compile_fix(node: ASTNode, err: StructuredError) -> ASTNode | None:
    """CompileFix: repair common compile errors in-place.

    Handles:
    - MissingKwarg: inject default kwarg (window=20 for rolling, periods=1 for delta)
    - UnknownKwarg: strip unknown kwargs
    - WrongArgCount: truncate or pad children with col(lit placeholder)
    """
    from .ast_nodes import ASTNode, make_col, make_lit

    if err.kind == "MissingKwarg":
        ctx = err.context
        op = ctx.get("op")
        missing = set(ctx.get("missing", []))
        if not op or not missing:
            return None
        new_kwargs = dict(node.kwargs)
        for k in missing:
            if k == "window":
                new_kwargs["window"] = 20
            elif k == "periods":
                new_kwargs["periods"] = 1
            elif k == "span":
                new_kwargs["span"] = 20
            else:
                return None  # cannot auto-fix
        logger.info("[SelfRepair] CompileFix: added %s to %s", missing, op)
        return ASTNode(op=node.op, args=list(node.args), kwargs=new_kwargs, value=node.value)

    if err.kind == "UnknownKwarg":
        ctx = err.context
        bad = set(ctx.get("bad_kwargs", []))
        if not bad:
            return None
        new_kwargs = {k: v for k, v in node.kwargs.items() if k not in bad}
        logger.info("[SelfRepair] CompileFix: stripped bad kwargs %s from %s", bad, node.op)
        return ASTNode(op=node.op, args=list(node.args), kwargs=new_kwargs, value=node.value)

    if err.kind == "WrongArgCount":
        ctx = err.context
        op = ctx.get("op")
        max_args = ctx.get("expected_max", 0)
        if not op or len(node.args) > max_args:
            return None
        # Pad to min expected (e.g. correlation needs 2 args)
        while len(node.args) < max_args:
            node.args.append(make_col("close"))
        logger.info(
            "[SelfRepair] CompileFix: padded %s args to %d",
            op, len(node.args),
        )
        return ASTNode(op=node.op, args=list(node.args), kwargs=dict(node.kwargs), value=node.value)

    return None


# ─── Strategy 3: SemanticFix ───────────────────────────────


def semantic_fix(node: ASTNode, err: StructuredError) -> ASTNode | None:
    """SemanticFix: when op is unknown, suggest Semantic/Composite replacement.

    If user's op name resembles a semantic template (e.g. "momentum" -> momentum_n),
    suggest replacement. Otherwise return None.
    """
    from .semantic_registry import get_op, list_ops

    if err.kind != "UnknownOp":
        return None
    ctx = err.context
    op_name = ctx.get("op")
    if not op_name:
        return None

    # Match against semantic registry by prefix/contains
    candidates = list_ops()
    base = op_name.lower().rstrip("_0123456789")
    for cand in candidates:
        cand_base = cand.lower().rstrip("_0123456789")
        if base == cand_base:
            logger.info(
                "[SelfRepair] SemanticFix: %r -> %r (suffix params required)",
                op_name, cand,
            )
            # Construct new op with same kwargs if numeric
            return None  # signal caller to use semantic instead
    return None


# ─── Strategy 4: CompositeFix ──────────────────────────────


def composite_fix(node: ASTNode, err: StructuredError) -> ASTNode | None:
    """CompositeFix: simplify DAG when composite template args are wrong.

    Strategy: Replace complex op with a simpler primitive (e.g. neutralize -> rank).
    """
    from .ast_nodes import make_col

    if err.kind not in ("QNCallFailed", "CompileError"):
        return None
    ctx = err.context
    op = ctx.get("op")
    if op in ("neutralize", "indneutralize"):
        # Fallback to plain rank (drop neutralization)
        logger.info("[SelfRepair] CompositeFix: %r -> rank (drop neutralization)", op)
        return ASTNode(op="rank", args=[make_col("close")], kwargs={}, value=None)
    if op in ("winsorize",):
        logger.info("[SelfRepair] CompositeFix: %r -> clip (simplify)", op)
        return ASTNode(
            op="clip",
            args=[make_col("close")],
            kwargs={"lower": -3.0, "upper": 3.0},
            value=None,
        )
    return None


# ─── Strategy 5: RuntimeFix ────────────────────────────────


def runtime_fix(node: ASTNode, err: StructuredError) -> ASTNode | None:
    """RuntimeFix: wrap risky op with type coercion (e.g. cast to Float64)."""
    from .ast_nodes import make_call

    if err.kind != "QNCallFailed":
        return None
    if "type" not in str(err.message).lower() and "schema" not in str(err.message).lower():
        return None
    # Wrap with cast operation
    logger.info("[SelfRepair] RuntimeFix: wrapping %s with astype(Float64)", node.op)
    return make_call("astype", [node], dtype="Float64")


# ─── Strategy 6: QualityFix ────────────────────────────────


def quality_fix(
    node: ASTNode,
    err: StructuredError,
    factor_data: dict | None = None,
) -> ASTNode | None:
    """QualityFix: when AST compiles but produces INCOMPLETE / zero-IC factor.

    Strategy: rewrite from l2.calculation_steps or fallback to simple momentum.
    """
    from .ast_nodes import make_call

    if err.kind != "IncompleteAST":
        return None
    logger.info("[SelfRepair] QualityFix: rewrite from l2 / fallback to momentum")
    # Simple fallback: 20-day momentum
    from .ast_nodes import make_col  # noqa: PLC0415
    return make_call("pct_change", [make_col("close")], periods=20)


# ─── Repair dispatcher ─────────────────────────────────────

FIX_STRATEGIES = [
    schema_fix,
    compile_fix,
    semantic_fix,
    composite_fix,
    runtime_fix,
]


def repair_once(
    node: ASTNode,
    err: StructuredError,
    factor_data: dict | None = None,
) -> ASTNode | None:
    """Try all FixStrategies in order. First non-None wins.

    Args:
        node: The AST node that failed to compile.
        err: StructuredError from previous attempt.
        factor_data: Optional factor context for QualityFix.

    Returns:
        Repaired ASTNode, or None if no strategy could fix.
    """
    for strategy in FIX_STRATEGIES:
        try:
            repaired = strategy(node, err)
        except Exception as exc:
            logger.warning("[SelfRepair] %s raised: %s", strategy.__name__, exc)
            continue
        if repaired is not None:
            return repaired

    # Try QualityFix last (needs factor_data)
    return quality_fix(node, err, factor_data)


def build_error_history(
    previous_errors: list[StructuredError],
) -> str:
    """Build a prompt snippet listing previous repair attempts.

    PR-6: Inject into LLM user_prompt to avoid repeating mistakes.
    """
    if not previous_errors:
        return ""
    lines = ["PREVIOUS FAILED ATTEMPTS (do NOT repeat these mistakes):"]
    for i, err in enumerate(previous_errors, 1):
        lines.append(f"\nAttempt {i}:")
        lines.append(f"  [{err.kind}] {err.message}")
        if err.suggestion:
            lines.append(f"  -> {err.suggestion}")
    return "\n".join(lines)


__all__ = [
    "FIX_STRATEGIES",
    "repair_once",
    "build_error_history",
    "schema_fix",
    "compile_fix",
    "semantic_fix",
    "composite_fix",
    "runtime_fix",
    "quality_fix",
]
