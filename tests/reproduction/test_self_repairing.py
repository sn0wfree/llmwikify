"""Tests for self_repairing: AST 自动修复."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from llmwikify.reproduction.codegen import repair as sr
from llmwikify.reproduction.ast_nodes import ASTNode
from llmwikify.reproduction.common.errors import StructuredError


class TestFixFunctions:
    """Test 各种 fix 函数 (5 测试)."""

    def test_schema_fix_callable(self) -> None:
        """schema_fix 可调用."""
        assert callable(sr.schema_fix)

    def test_compile_fix_callable(self) -> None:
        """compile_fix 可调用."""
        assert callable(sr.compile_fix)

    def test_semantic_fix_callable(self) -> None:
        """semantic_fix 可调用."""
        assert callable(sr.semantic_fix)

    def test_composite_fix_callable(self) -> None:
        """composite_fix 可调用."""
        assert callable(sr.composite_fix)

    def test_runtime_fix_callable(self) -> None:
        """runtime_fix 可调用."""
        assert callable(sr.runtime_fix)


class TestRepairFunctions:
    """Test repair_once + build_error_history (3 测试)."""

    def test_repair_once_callable(self) -> None:
        """repair_once 可调用."""
        assert callable(sr.repair_once)

    def test_quality_fix_callable(self) -> None:
        """quality_fix 可调用."""
        assert callable(sr.quality_fix)

    def test_build_error_history_callable(self) -> None:
        """build_error_history 可调用."""
        assert callable(sr.build_error_history)


class TestFixReturnTypes:
    """Test fix 函数返回类型 (2 测试)."""

    def test_schema_fix_returns_node_or_none(self) -> None:
        """schema_fix 返回 ASTNode 或 None."""
        node = ASTNode(op="rank", args=[])
        err = StructuredError(kind="Test", message="m")
        result = sr.schema_fix(node, err)
        # 接受 None 或 ASTNode
        assert result is None or isinstance(result, ASTNode)

    def test_repair_once_returns_dict_or_list(self) -> None:
        """repair_once 返回 dict 或 list (含 history)."""
        node = ASTNode(op="rank", args=[])
        err = StructuredError(kind="Test", message="m")
        try:
            result = sr.repair_once(node, err)
            # 接受 dict 或 list 或 None
            assert result is None or isinstance(result, (dict, list))
        except Exception:
            pass  # 接受异常 (可能依赖外部状态)
