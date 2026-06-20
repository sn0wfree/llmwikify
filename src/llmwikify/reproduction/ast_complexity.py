"""AST complexity checker — flag false-positive compilations.

LLM sometimes emits simplified ASTs (e.g. only `diff` instead of full
`rank(diff(returns, 3)) * correlation(open, volume, 10)`). The AST compiles
successfully but doesn't match the L2 step count from the factor YAML.

This module computes complexity metrics and returns a verdict:
- COMPLETE: AST likely represents the full expression
- INCOMPLETE: AST too small relative to L2 steps, re-prompt needed

Reference: docs/designs/llm_compile_loop_v4.md (Stage 2.5)
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ast_nodes import ASTNode


class ComplexityVerdict(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


def count_nodes(node: ASTNode) -> int:
    """Count total nodes in AST (recursive)."""
    return 1 + sum(count_nodes(c) for c in node.args)


def collect_ops(node: ASTNode, ops: set[str] | None = None) -> set[str]:
    """Collect all unique ops in AST."""
    if ops is None:
        ops = set()
    ops.add(node.op)
    for c in node.args:
        collect_ops(c, ops)
    return ops


def compute_complexity(
    node: ASTNode,
    l2_step_count: int = 0,
) -> tuple[int, int, int, int, int]:
    """Compute complexity metrics for an AST.

    Returns:
        (total_nodes, unique_ops, max_depth, expected_min_nodes, expected_min_ops)
    """
    total = count_nodes(node)
    ops = collect_ops(node)

    # Expected: each L2 step typically needs 2-4 nodes (e.g. col + sub + mul)
    # So expected_min_nodes = l2_step_count * 2
    # If no L2 steps known, use absolute min of 3 nodes (1 leaf + 1 op + 1 leaf)
    expected_min_nodes = max(3, l2_step_count * 2)
    # Each step uses at least 1 unique op, so expected_min_ops = l2_step_count
    # Without L2 steps, expect at least 2 unique ops (e.g. rank + col)
    expected_min_ops = max(2, l2_step_count)

    # Compute max depth (longest chain)
    def _depth(n: ASTNode) -> int:
        if not n.args:
            return 1
        return 1 + max((_depth(c) for c in n.args), default=0)
    max_depth = _depth(node)

    return total, len(ops), max_depth, expected_min_nodes, expected_min_ops


def check_complexity(
    node: ASTNode,
    l2_step_count: int = 0,
) -> tuple[ComplexityVerdict, str]:
    """Check if AST is complete (matches L2 steps) or incomplete.

    Returns:
        (verdict, message)
        - COMPLETE: AST complexity meets minimum requirements
        - INCOMPLETE: AST too simple, likely truncated
    """
    total, unique_ops, max_depth, exp_min_nodes, exp_min_ops = compute_complexity(
        node, l2_step_count
    )

    if total < exp_min_nodes:
        return (
            ComplexityVerdict.INCOMPLETE,
            f"AST has only {total} nodes, expected at least {exp_min_nodes} "
            f"(L2 has {l2_step_count} steps; each typically needs 2+ nodes). "
            f"Your output is likely truncated. Please output the COMPLETE expression "
            f"with all calculation steps, not just the first one.",
        )

    if unique_ops < exp_min_ops:
        return (
            ComplexityVerdict.INCOMPLETE,
            f"AST uses only {unique_ops} unique ops, expected at least {exp_min_ops} "
            f"(L2 has {l2_step_count} steps). Your output is likely missing key "
            f"calculation steps. Please include the full formula with all operations.",
        )

    return (ComplexityVerdict.COMPLETE, "OK")


__all__ = [
    "ComplexityVerdict",
    "check_complexity",
    "compute_complexity",
    "count_nodes",
    "collect_ops",
]
