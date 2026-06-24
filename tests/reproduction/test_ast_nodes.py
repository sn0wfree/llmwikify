"""Tests for ast_nodes: ASTNode dataclass + factory functions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llmwikify.reproduction.codegen.ast.nodes import (
    ASTNode, NodeType, OpName,
    make_col, make_lit, make_binary, make_unary, make_call,
    is_known_op, get_op_spec,
)


class TestASTNodeConstruction:
    """Test ASTNode 构造 (3 测试)."""

    def test_basic_node(self) -> None:
        """基本 ASTNode 节点."""
        node = ASTNode(op="rank")
        assert node.op == "rank"
        assert node.args == []
        assert node.kwargs == {}
        assert node.value is None

    def test_node_with_args(self) -> None:
        """带 args 的 ASTNode."""
        col = make_col("close")
        node = ASTNode(op="rank", args=[col])
        assert len(node.args) == 1
        assert node.args[0].op == "col"

    def test_node_with_value(self) -> None:
        """lit 节点带 value."""
        node = ASTNode(op="lit", value=42)
        assert node.value == 42

    def test_invalid_node_extra_field_raises(self) -> None:
        """extra 字段抛 ValidationError (model_config=extra=forbid)."""
        with pytest.raises(ValidationError):
            ASTNode(op="rank", invalid_field="x")


class TestFactoryFunctions:
    """Test 工厂函数 (5 测试)."""

    def test_make_col(self) -> None:
        """make_col 返回 col 节点."""
        node = make_col("close")
        assert node.op == "col"
        assert node.value == "close"

    def test_make_lit(self) -> None:
        """make_lit 返回 lit 节点."""
        node = make_lit(3.14)
        assert node.op == "lit"
        assert node.value == 3.14

    def test_make_binary(self) -> None:
        """make_binary 返回二元算子节点."""
        node = make_binary("add", make_col("a"), make_col("b"))
        assert node.op == "add"
        assert len(node.args) == 2

    def test_make_unary(self) -> None:
        """make_unary 返回一元算子节点."""
        node = make_unary("abs", make_col("x"))
        assert node.op == "abs"
        assert len(node.args) == 1

    def test_make_call_with_kwargs(self) -> None:
        """make_call 接受 kwargs."""
        node = make_call("rolling_mean", [make_col("close")], window=5)
        assert node.op == "rolling_mean"
        assert node.kwargs == {"window": 5}


class TestOpRegistry:
    """Test is_known_op + get_op_spec (3 测试)."""

    def test_known_op(self) -> None:
        """已知 op 返回 True."""
        assert is_known_op("rank") is True
        assert is_known_op("ts_mean") is True
        assert is_known_op("abs") is True

    def test_unknown_op_returns_false(self) -> None:
        """未知 op 返回 False."""
        assert is_known_op("nonexistent_op_xyz") is False

    def test_get_op_spec_known(self) -> None:
        """get_op_spec 返回 (arity, ...) 元组."""
        spec = get_op_spec("rank")
        assert spec is not None
        assert len(spec) >= 2  # (arity, n_inputs, ...)

    def test_get_op_spec_unknown_raises(self) -> None:
        """get_op_spec 未知 op 抛 ValueError."""
        with pytest.raises(ValueError):
            get_op_spec("nonexistent_op_xyz")


class TestNodeType:
    """Test NodeType / OpName enums (1 测试)."""

    def test_node_type_is_str_enum(self) -> None:
        """NodeType 是 str Enum."""
        from llmwikify.reproduction.codegen.ast.nodes import NodeType
        assert issubclass(NodeType, str)
        # 至少有 COL 和 LIT
        assert hasattr(NodeType, "COL")
        assert hasattr(NodeType, "LIT")
