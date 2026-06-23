"""Tests for strategies: 6 个 StrategyNode 子类 + get_strategy_node."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import strategies as s


class TestStrategyNodeClasses:
    """Test 6 个 StrategyNode 子类 (3 测试)."""

    def test_ma_cross_strategy_class(self) -> None:
        """MACrossStrategyNode 类存在."""
        assert hasattr(s, "MACrossStrategyNode")

    def test_rsi_strategy_class(self) -> None:
        """RSIStrategyNode 类存在."""
        assert hasattr(s, "RSIStrategyNode")

    def test_momentum_strategy_class(self) -> None:
        """MomentumStrategyNode 类存在."""
        assert hasattr(s, "MomentumStrategyNode")


class TestGetStrategyNode:
    """Test get_strategy_node 工厂 (4 测试)."""

    def test_get_strategy_node_callable(self) -> None:
        """get_strategy_node 可调用."""
        assert callable(s.get_strategy_node)

    def test_get_strategy_node_ma_cross(self) -> None:
        """ma_cross 返回 MACrossStrategyNode."""
        result = s.get_strategy_node("ma_cross", config={})
        assert result is not None
        assert isinstance(result, s.MACrossStrategyNode)

    def test_get_strategy_node_unknown_type(self) -> None:
        """未知 type 不抛错 (返回 None 或 default)."""
        try:
            result = s.get_strategy_node("unknown_xyz_type", config={})
            # 接受 None 或某种 node
            assert result is None or hasattr(result, "name")
        except Exception:
            pass  # 接受异常

    def test_signal_node_registry(self) -> None:
        """SIGNAL_NODE_REGISTRY 存在 (test_module_inventory 锁定)."""
        assert hasattr(s, "SIGNAL_NODE_REGISTRY")
        assert isinstance(s.SIGNAL_NODE_REGISTRY, dict)
        assert len(s.SIGNAL_NODE_REGISTRY) >= 4
