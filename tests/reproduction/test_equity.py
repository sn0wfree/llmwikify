"""Tests for build_equity_curve — P5 single source of truth for equity reconstruction.

Guards that the extracted function in ``reproduction/equity.py`` is byte-equal
to the previous inlined implementation in ``backtest_pkg/run_backtest.py``.
"""

from __future__ import annotations

import pandas as pd

from llmwikify.reproduction.equity import build_equity_curve


def _make_data(n: int = 10, close: float = 100.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with n bars."""
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Close": [close + i for i in range(n)],
    })


def test_empty_data_returns_empty_list() -> None:
    """Empty input data must yield empty equity curve."""
    assert build_equity_curve([], pd.DataFrame(), 1_000_000.0) == []


def test_no_trades_keeps_initial_cash_constant() -> None:
    """Without any trades, equity must equal initial_cash at every bar."""
    data = _make_data(n=5, close=100.0)
    equity = build_equity_curve([], data, 1_000_000.0)
    assert len(equity) == 5
    for pt in equity:
        assert pt["value"] == 1_000_000.0


def test_buy_trade_deducts_cash_and_adds_position() -> None:
    """A buy trade at bar 0 must reduce cash and grow position into bar 1's equity."""
    data = _make_data(n=3, close=100.0)
    trades = [{"date": "2024-01-01", "action": "buy", "quantity": 100.0, "price": 100.0}]
    equity = build_equity_curve(trades, data, 1_000_000.0)

    # Bar 0: trade executes before close, cash drops by 10_000, position = 100
    # equity = (1_000_000 - 10_000) + 100 * 100 = 1_000_000 (unchanged at trade price)
    assert equity[0]["value"] == 1_000_000.0
    # Bar 1: close = 101, position = 100, cash = 990_000
    # equity = 990_000 + 100 * 101 = 1_000_100
    assert equity[1]["value"] == 1_000_100.0


def test_sell_trade_adds_cash_and_reduces_position() -> None:
    """A sell trade must increase cash and reduce position; subsequent bars reflect flat equity."""
    data = _make_data(n=4, close=100.0)
    trades = [
        {"date": "2024-01-01", "action": "buy", "quantity": 100.0, "price": 100.0},
        {"date": "2024-01-03", "action": "sell", "quantity": 100.0, "price": 102.0},
    ]
    equity = build_equity_curve(trades, data, 1_000_000.0)

    # Bar 0 (buy at 100): cash = 990_000, position = 100, equity at close=100 = 1_000_000
    assert equity[0]["value"] == 1_000_000.0
    # Bar 2 (sell at 102): cash = 990_000 + 10_200 = 1_000_200, position = 0
    # equity at close=102 = 1_000_200
    assert equity[2]["value"] == 1_000_200.0
    # Bar 3 (no position): cash = 1_000_200, equity = 1_000_200
    assert equity[3]["value"] == 1_000_200.0


def test_final_equity_matches_cash_plus_position_times_close() -> None:
    """P3 invariant: equity at last bar = cash + position * close (within rounding)."""
    data = _make_data(n=20, close=50.0)
    trades = [
        {"date": "2024-01-05", "action": "buy", "quantity": 200.0, "price": 50.0},
        {"date": "2024-01-15", "action": "sell", "quantity": 100.0, "price": 55.0},
    ]
    equity = build_equity_curve(trades, data, 500_000.0)

    last = equity[-1]
    # Expected: cash after = 500_000 - 10_000 + 5_500 = 495_500; position = 100
    # close at last bar = 50 + 19 = 69
    # equity = 495_500 + 100 * 69 = 502_400
    assert last["value"] == 502_400.0
    # All values are rounded to 2 decimals
    for pt in equity:
        assert isinstance(pt["value"], float)
        # 2 decimal rounding
        assert pt["value"] == round(pt["value"], 2)
