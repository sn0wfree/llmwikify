"""Equity curve reconstruction for backtest results.

Single source of truth (P5: 算法单一实现) for turning a sequence of
trades + OHLCV bars into a daily equity time series. Referenced from
``docs/plan/reproduction-realignment.md`` §4.8.

Usage:
    from llmwikify.reproduction.equity import build_equity_curve

    equity = build_equity_curve(trades=trades, data=ohlcv, initial_cash=1_000_000)
    # → [{"date": "2024-01-01", "value": 1000000.0}, ...]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_equity_curve(
    trades: list[Any],
    data: Any,
    initial_cash: float,
) -> list[dict[str, Any]]:
    """Reconstruct daily equity time series from trades and price data.

    Iterates over each bar in ``data``, tracks open position, and computes
    ``equity = cash + position * close_price`` at each bar.

    Args:
        trades: List of trade objects (dict or namespace) with
            ``date`` / ``action`` / ``quantity`` / ``price`` fields.
        data: DataFrame-like with ``date`` and ``Close`` columns.
        initial_cash: Starting cash (e.g. 1,000,000).

    Returns:
        List of ``{"date": "YYYY-MM-DD", "value": float}`` dicts, one per
        bar in ``data`` (in the order they appear).
    """
    if data is None or len(data) == 0:
        return []

    dates = data["date"].tolist()
    closes = data["Close"].tolist()

    cash = initial_cash
    position = 0.0
    equity_list: list[dict[str, Any]] = []

    trades_by_date: dict[str, list[Any]] = {}
    for t in trades:
        t_date = ""
        if isinstance(t, dict):
            t_date = str(t.get("date", t.get("create_date", "")))[:10]
        elif hasattr(t, "date"):
            t_date = str(getattr(t, "date", ""))[:10]
        if t_date:
            trades_by_date.setdefault(t_date, []).append(t)

    for _i, (date_str, close) in enumerate(zip(dates, closes, strict=False)):
        for t in trades_by_date.get(date_str, []):
            action = ""
            qty = 0.0
            price = 0.0
            if isinstance(t, dict):
                action = str(t.get("action", t.get("side", ""))).lower()
                qty = float(t.get("quantity", t.get("qty", 0)))
                price = float(t.get("price", 0))
            elif hasattr(t, "action"):
                action = str(getattr(t, "action", "")).lower()
                qty = float(getattr(t, "quantity", 0))
                price = float(getattr(t, "price", 0))

            if "buy" in action:
                cost = qty * price
                if cost <= cash:
                    cash -= cost
                    position += qty
            elif "sell" in action:
                cash += qty * price
                position -= qty

        equity = cash + position * close
        equity_list.append({"date": date_str, "value": round(equity, 2)})

    return equity_list


__all__ = ["build_equity_curve"]
