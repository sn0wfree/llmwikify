"""Tests for ast_complexity: ASTNode 复杂度分析."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import ast_complexity as ac
from llmwikify.reproduction.ast_nodes import ASTNode, make_col, make_lit


def _make_rank() -> ASTNode:
    """rank('close') 简单 AST."""
    return ASTNode(op="rank", args=[make_col("close")])


def _make_nested() -> ASTNode:
    """rank(ts_mean(close, 5)) 嵌套 AST."""
    inner = ASTNode(op="ts_mean", args=[make_col("close")], kwargs={"window": 5})
    return ASTNode(op="rank", args=[inner])


class TestComputeComplexity:
    """Test compute_complexity (4 测试)."""

    def test_simple_ast(self) -> None:
        """简单 AST 返回 5-tuple (total, unique_ops, depth, ...)."""
        result = ac.compute_complexity(_make_rank())
        assert isinstance(result, tuple)
        assert len(result) == 5
        total, unique_ops, depth, _, _ = result
        assert total == 2  # rank + col
        assert unique_ops == 2  # {rank, col}
        assert depth >= 1

    def test_nested_ast_more_complex(self) -> None:
        """嵌套 AST 比简单 AST 更复杂."""
        simple = ac.compute_complexity(_make_rank())
        nested = ac.compute_complexity(_make_nested())
        assert nested[0] > simple[0]  # total_nodes 多
        assert nested[1] > simple[1]  # unique_ops 多
        assert nested[2] > simple[2]  # max_depth 深

    def test_returns_five_ints(self) -> None:
        """返回 5 个 int."""
        result = ac.compute_complexity(_make_rank())
        for x in result:
            assert isinstance(x, int)

    def test_with_l2_step_count(self) -> None:
        """l2_step_count 参数影响 expected min."""
        result = ac.compute_complexity(_make_rank(), l2_step_count=2)
        # 第 4 个元素 expected_min_nodes = max(3, 2*2) = 4
        assert result[3] == 4
        # 第 5 个元素 expected_min_ops = max(2, 2) = 2
        assert result[4] == 2


class TestCountAndCollect:
    """Test count_nodes + collect_ops (2 测试)."""

    def test_count_nodes(self) -> None:
        """count_nodes 返回 AST 节点总数."""
        assert ac.count_nodes(_make_rank()) == 2
        assert ac.count_nodes(_make_nested()) == 3

    def test_collect_ops(self) -> None:
        """collect_ops 收集所有 op 名称."""
        ops = ac.collect_ops(_make_nested())
        assert "rank" in ops
        assert "ts_mean" in ops
        assert "col" in ops


class TestCheckComplexity:
    """Test check_complexity (1 测试)."""

    def test_returns_verdict_tuple(self) -> None:
        """check_complexity 返回 (verdict, message) tuple."""
        from llmwikify.reproduction.ast_complexity import ComplexityVerdict
        result = ac.check_complexity(_make_rank())
        assert isinstance(result, tuple)
        assert len(result) == 2
        verdict, message = result
        assert isinstance(verdict, ComplexityVerdict)
        assert isinstance(message, str)
