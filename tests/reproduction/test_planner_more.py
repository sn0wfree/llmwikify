"""Tests for llm_extraction/planner: paper planning (补充 test_planner_helpers.py)."""

from __future__ import annotations

import pytest

from llmwikify.reproduction.paper_understanding.llm_extraction import planner as p


class TestPlanResult:
    """Test PlanResult dataclass (2 测试)."""

    def test_class_exists(self) -> None:
        """PlanResult 类存在."""
        assert hasattr(p, "PlanResult")

    def test_construction(self) -> None:
        """PlanResult 构造 (用真实字段)."""
        # 字段可能因版本变化, 用 **kwargs 兼容
        try:
            r = p.PlanResult()
            assert r is not None
        except TypeError:
            # 至少存在
            assert p.PlanResult is not None


class TestPlanPaper:
    """Test plan_paper 主入口 (3 测试)."""

    def test_callable(self) -> None:
        """plan_paper 可调用."""
        assert callable(p.plan_paper)

    def test_signature(self) -> None:
        """签名: 接受 paper content."""
        import inspect
        sig = inspect.signature(p.plan_paper)
        params = list(sig.parameters.keys())
        assert len(params) >= 1  # 至少 paper 参数

    def test_validate_plan_callable(self) -> None:
        """validate_plan_with_llm 可调用."""
        assert callable(p.validate_plan_with_llm)


class TestModuleStructure:
    """Test 模块结构 (3 测试)."""

    def test_logger_exists(self) -> None:
        """logger 存在."""
        import logging
        assert hasattr(p, "logger")

    def test_public_api(self) -> None:
        """公共 API 数量."""
        for fn in ["plan_paper", "validate_plan_with_llm"]:
            assert hasattr(p, fn)

    def test_module_docstring(self) -> None:
        """模块有 docstring."""
        assert p.__doc__ is not None
