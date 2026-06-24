"""Tests for factor_backtest.py — factor backtest engine."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.backtest_pkg.factor_backtest import (
    _compute_factor_values,
    run_factor_backtest,
)


def _make_data(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({
        "date": dates,
        "open": close + rng.normal(0, 0.5, n),
        "high": close + abs(rng.normal(0, 1, n)),
        "low": close - abs(rng.normal(0, 1, n)),
        "close": close,
        "volume": rng.integers(1_000_000, 10_000_000, n).astype(float),
    })


def test_compute_factor_momentum():
    data = _make_data(60)
    factor = _compute_factor_values(data, "momentum", {"lookback": 10})
    assert len(factor) == 60
    assert not factor.iloc[:10].notna().any()  # NaN for first 10 periods
    assert factor.iloc[10:].notna().any()


def test_compute_factor_volatility():
    data = _make_data(60)
    factor = _compute_factor_values(data, "volatility", {"period": 20})
    assert len(factor) == 60
    assert factor.iloc[25:].notna().any()


def test_compute_factor_ma_cross():
    data = _make_data(60)
    factor = _compute_factor_values(data, "ma_cross", {"fast": 5, "slow": 20})
    assert len(factor) == 60
    assert factor.iloc[25:].notna().any()


def test_compute_factor_rsi():
    data = _make_data(60)
    factor = _compute_factor_values(data, "rsi", {"period": 14})
    assert len(factor) == 60
    assert factor.iloc[20:].notna().any()


def test_compute_factor_unknown():
    data = _make_data(60)
    factor = _compute_factor_values(data, "unknown_type", {"period": 10})
    assert len(factor) == 60  # Falls back to momentum


def test_run_factor_backtest_momentum():
    data = _make_data(100)
    result = run_factor_backtest(data, "momentum", {"lookback": 10})
    assert result is not None
    assert isinstance(result.ic_mean, float)
    assert isinstance(result.icir, float)
    assert isinstance(result.win_rate, float)
    assert isinstance(result.quantile_returns, dict)
    assert isinstance(result.ic_series, list)
    assert isinstance(result.quantile_curves, dict)


def test_run_factor_backtest_volatility():
    data = _make_data(100)
    result = run_factor_backtest(data, "volatility", {"period": 20})
    assert result is not None
    assert result.ic_std >= 0


def test_run_factor_backtest_ma_cross():
    data = _make_data(100)
    result = run_factor_backtest(data, "ma_cross", {"fast": 5, "slow": 20})
    assert result is not None
    assert result.max_drawdown >= 0


def test_run_factor_backtest_empty_data():
    result = run_factor_backtest(pd.DataFrame(), "momentum", {})
    assert result.ic_mean == 0.0
    assert result.quantile_returns == {}


def test_run_factor_backtest_quantile_groups():
    data = _make_data(100)
    result = run_factor_backtest(data, "momentum", {"lookback": 10}, n_groups=5)
    # Should have G1-G5
    assert "G1" in result.quantile_returns
    assert "G5" in result.quantile_returns


def test_run_factor_backtest_ic_series_format():
    data = _make_data(60)
    result = run_factor_backtest(data, "momentum", {"lookback": 10})
    if result.ic_series:
        pt = result.ic_series[0]
        assert "date" in pt
        assert "ic" in pt


def test_run_factor_backtest_quantile_curves_format():
    data = _make_data(60)
    result = run_factor_backtest(data, "momentum", {"lookback": 10})
    if result.quantile_curves.get("G1"):
        pt = result.quantile_curves["G1"][0]
        assert "date" in pt
        assert "value" in pt
