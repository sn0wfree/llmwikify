"""Tests for ast_compiler: ASTNode → polars Expr."""

from __future__ import annotations

import polars as pl
import pytest

from llmwikify.reproduction import ast_compiler as ac
from llmwikify.reproduction.ast_compiler import CompileError
from llmwikify.reproduction.ast_nodes import ASTNode, make_col, make_lit


def _make_rank() -> ASTNode:
    """rank('close')."""
    return ASTNode(op="rank", args=[make_col("close")])


def _make_lit() -> ASTNode:
    """lit(42)."""
    return ASTNode(op="lit", args=[], value=42)


class TestCompileAst:
    """Test compile_ast (5 测试)."""

    def test_compile_simple_op(self) -> None:
        """简单 op 编译为 polars Expr."""
        result = ac.compile_ast(_make_rank())
        assert isinstance(result, pl.Expr)

    def test_unknown_op_raises_compile_error(self) -> None:
        """未知 op 抛 CompileError."""
        node = ASTNode(op="totally_made_up_op", args=[])
        with pytest.raises(CompileError):
            ac.compile_ast(node)

    def test_compile_lit(self) -> None:
        """lit 节点编译成功."""
        result = ac.compile_ast(_make_lit())
        assert isinstance(result, pl.Expr)

    def test_compile_nested(self) -> None:
        """嵌套 AST 编译成功."""
        inner = ASTNode(op="ts_mean", args=[make_col("close")], kwargs={"window": 5})
        outer = ASTNode(op="rank", args=[inner])
        result = ac.compile_ast(outer)
        assert isinstance(result, pl.Expr)

    def test_compile_error_has_message(self) -> None:
        """CompileError 异常有非空 message."""
        node = ASTNode(op="invalid_op_xyz", args=[])
        with pytest.raises(CompileError) as exc_info:
            ac.compile_ast(node)
        # 异常对象有 message 属性或 str()
        assert str(exc_info.value) or getattr(exc_info.value, "message", None)


class TestGetOpSpec:
    """Test get_op_spec + is_known_op (2 测试)."""

    def test_known_op_returns_spec(self) -> None:
        """已知 op 返回 spec."""
        # 找一个真实存在的 op
        assert ac.is_known_op("rank") is True
        assert ac.is_known_op("ts_mean") is True

    def test_unknown_op_raises(self) -> None:
        """未知 op 抛 ValueError."""
        with pytest.raises(ValueError):
            ac.get_op_spec("totally_made_up_op_xyz")
