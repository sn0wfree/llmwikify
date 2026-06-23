"""Tests for schemas: 4 个 dataclass."""

from __future__ import annotations

import pytest

from llmwikify.reproduction import schemas as s


class TestBacktestResult:
    """Test BacktestResult dataclass (3 测试)."""

    def test_default_construction(self) -> None:
        """BacktestResult() 默认构造."""
        r = s.BacktestResult()
        assert r is not None

    def test_to_dict(self) -> None:
        """to_dict() 序列化."""
        r = s.BacktestResult()
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_with_equity_curve(self) -> None:
        """BacktestResult 接受 equity_curve."""
        r = s.BacktestResult(equity_curve=[{"date": "2024-01-01", "value": 100000.0}])
        assert len(r.equity_curve) == 1


class TestWikiFactor:
    """Test WikiFactor (2 测试)."""

    def test_construction(self) -> None:
        """WikiFactor 构造 (用真实字段)."""
        f = s.WikiFactor(name="momentum", factor_class="alpha", factor_params={"window": 20})
        assert f.name == "momentum"
        assert f.factor_class == "alpha"

    def test_to_dict(self) -> None:
        """to_dict() 序列化."""
        f = s.WikiFactor(name="x", factor_class="alpha", factor_params={})
        d = f.to_dict()
        assert d["name"] == "x"


class TestWikiStrategy:
    """Test WikiStrategy (1 测试)."""

    def test_construction_and_to_dict(self) -> None:
        """WikiStrategy 构造 + to_dict."""
        st = s.WikiStrategy(name="strat1", strategy_class="factor_ranking")
        d = st.to_dict()
        assert d["name"] == "strat1"


class TestFactorBacktestResult:
    """Test FactorBacktestResult (2 测试)."""

    def test_construction(self) -> None:
        """FactorBacktestResult 默认构造 (字段很多, 全部 default)."""
        r = s.FactorBacktestResult()
        assert r is not None
        assert r.ic_mean == 0.0 or r.ic_mean is None  # 看 default

    def test_to_dict(self) -> None:
        """to_dict() 序列化."""
        r = s.FactorBacktestResult()
        d = r.to_dict()
        assert isinstance(d, dict)
        assert "ic_mean" in d


class TestModuleStructure:
    """Test 模块结构 (1 测试)."""

    def test_all_classes_have_to_dict(self) -> None:
        """所有 4 个类都有 to_dict()."""
        for cls in [s.BacktestResult, s.WikiFactor, s.WikiStrategy, s.FactorBacktestResult]:
            r = cls()
            assert hasattr(r, "to_dict"), f"{cls.__name__} missing to_dict"
