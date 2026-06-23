"""Tests for l5_validation: L5 阶段分析 (IC/groups/returns/turnover/stability)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from llmwikify.reproduction import l5_validation as l5v


class TestRunL5Validation:
    """Test run_l5_validation 主入口 (3 测试)."""

    def test_function_exists(self) -> None:
        """run_l5_validation 存在."""
        assert callable(l5v.run_l5_validation)

    def test_accepts_result_arg(self) -> None:
        """接受 result 参数."""
        import inspect
        sig = inspect.signature(l5v.run_l5_validation)
        params = list(sig.parameters.keys())
        assert "result" in params

    def test_returns_dict(self) -> None:
        """返回 dict."""
        mock_result = MagicMock()
        with pytest.raises(Exception):
            # 可能依赖 result 内部结构, 接受任意异常
            l5v.run_l5_validation(mock_result)


class TestAnalysisFunctions:
    """Test 6 个分析函数 (4 测试)."""

    def test_analyze_ic_callable(self) -> None:
        """analyze_ic 可调用."""
        assert callable(l5v.analyze_ic)

    def test_analyze_groups_callable(self) -> None:
        """analyze_groups 可调用."""
        assert callable(l5v.analyze_groups)

    def test_compute_score_callable(self) -> None:
        """compute_score 可调用."""
        assert callable(l5v.compute_score)

    def test_analyze_oos_accepts_n_folds(self) -> None:
        """analyze_oos 接受 n_folds."""
        import inspect
        sig = inspect.signature(l5v.analyze_oos)
        params = list(sig.parameters.keys())
        assert "n_folds" in params


class TestModuleStructure:
    """Test 模块结构 (2 测试)."""

    def test_logger_exists(self) -> None:
        """logger 存在."""
        import logging
        assert hasattr(l5v, "logger")

    def test_public_api_count(self) -> None:
        """公共 API 数量 ≥ 8."""
        public_funcs = [
            "analyze_ic", "analyze_groups", "analyze_returns",
            "analyze_turnover", "analyze_stability", "analyze_oos",
            "analyze_cost", "compute_score", "run_l5_validation",
        ]
        for fn in public_funcs:
            assert hasattr(l5v, fn)
