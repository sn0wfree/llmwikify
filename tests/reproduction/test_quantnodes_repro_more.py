"""Tests for quantnodes_repro: 因子回测主流程 (补充 test_factor_backtest.py 覆盖)."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import quantnodes_repro as qr


class TestClasses:
    """Test 数据类 (2 测试)."""

    def test_backtest_outcome_class(self) -> None:
        """BacktestOutcome 类存在."""
        assert hasattr(qr, "BacktestOutcome")

    def test_paper_backtest_report_class(self) -> None:
        """PaperBacktestReport 类存在."""
        assert hasattr(qr, "PaperBacktestReport")


class TestRunFactorBacktest:
    """Test run_factor_backtest 主入口 (3 测试)."""

    def test_callable(self) -> None:
        """run_factor_backtest 可调用."""
        assert callable(qr.run_factor_backtest)

    def test_signature(self) -> None:
        """签名: 接受 factor 信息."""
        import inspect
        sig = inspect.signature(qr.run_factor_backtest)
        params = list(sig.parameters.keys())
        # 应有 factor_name/code/h5_path 等
        assert len(params) >= 3

    def test_paper_backtest_callable(self) -> None:
        """run_paper_backtest 可调用."""
        assert callable(qr.run_paper_backtest)


class TestSaveReport:
    """Test save_report (2 测试)."""

    def test_callable(self) -> None:
        """save_report 可调用."""
        assert callable(qr.save_report)

    def test_module_imports(self) -> None:
        """模块可导入 + 公共 API."""
        public_funcs = ["run_factor_backtest", "run_paper_backtest", "save_report"]
        for fn in public_funcs:
            assert hasattr(qr, fn)
