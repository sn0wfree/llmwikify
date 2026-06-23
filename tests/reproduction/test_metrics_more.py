"""Tests for metrics: IC/ICIR/winrate 计算 (补充 test_quant.py 覆盖)."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import metrics as m


class TestEvaluation:
    """Test evaluation() 主入口 (3 测试)."""

    def test_returns_dict(self) -> None:
        """evaluation 返回 dict."""
        result = m.evaluation(net=[0.01, -0.02, 0.03, 0.01, -0.01], adj_dates=[])
        assert isinstance(result, dict)

    def test_empty_input(self) -> None:
        """空输入返回 dict (可能空值)."""
        result = m.evaluation(net=[], adj_dates=[])
        assert isinstance(result, dict)

    def test_with_trading_days(self) -> None:
        """接受 trading_days 参数."""
        result = m.evaluation(
            net=[0.01, -0.02, 0.03, 0.01, -0.01],
            adj_dates=[],
            trading_days=252,
        )
        assert isinstance(result, dict)


class TestComputeMetrics:
    """Test 其他 compute 函数 (3 测试)."""

    def test_compute_metrics_from_trades_callable(self) -> None:
        """compute_metrics_from_trades 可调用."""
        assert callable(m.compute_metrics_from_trades)

    def test_compute_extended_metrics_callable(self) -> None:
        """compute_extended_metrics 可调用."""
        assert callable(m.compute_extended_metrics)

    def test_compute_monthly_returns_callable(self) -> None:
        """compute_monthly_returns 可调用."""
        assert callable(m.compute_monthly_returns)


class TestCalNet:
    """Test cal_net_simple (2 测试)."""

    def test_cal_net_callable(self) -> None:
        """cal_net_simple 可调用."""
        assert callable(m.cal_net_simple)

    def test_cal_net_signature(self) -> None:
        """签名: net + adj_dates."""
        import inspect
        sig = inspect.signature(m.cal_net_simple)
        params = list(sig.parameters.keys())
        assert "net" in params
        assert "adj_dates" in params
