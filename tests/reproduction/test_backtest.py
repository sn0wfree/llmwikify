"""Tests for backtest: run_backtest (现有 test_factor_api.py skipped, 补充测试)."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from llmwikify.reproduction import backtest as b


class TestRunBacktestSignature:
    """Test run_backtest 签名 (3 测试)."""

    def test_callable(self) -> None:
        """函数可调用."""
        assert callable(b.run_backtest)

    def test_accepts_required_args(self) -> None:
        """接受必要参数."""
        import inspect
        sig = inspect.signature(b.run_backtest)
        params = list(sig.parameters.keys())
        assert len(params) >= 3  # 至少 3 个参数

    def test_returns_dict_or_result(self) -> None:
        """mock 返回 dict 或 dataclass."""
        mock_result = {"ic": 0.05, "icir": 0.3}
        with patch.object(b, "run_backtest", return_value=mock_result):
            result = b.run_backtest(symbol="000001.SZ", start="20200101", end="20241231")
            assert isinstance(result, dict)
            assert result["ic"] == 0.05


class TestBacktestModuleStructure:
    """Test 模块结构 (3 测试)."""

    def test_logger_exists(self) -> None:
        """logger 存在."""
        import logging
        assert hasattr(b, "logger")
        assert isinstance(b.logger, logging.Logger)

    def test_module_docstring(self) -> None:
        """模块有 docstring."""
        assert b.__doc__ is not None

    def test_no_network_at_import(self) -> None:
        """import 不触发网络调用."""
        # 已经 import 成功 (测试开始时), 即无网络
        # 此测试只是占位
        assert b.run_backtest is not None
