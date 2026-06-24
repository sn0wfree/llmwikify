"""QuantNodes StrategyNode subclasses for 6 signal types.

Each class extends QuantNodes' StrategyNode and implements _generate_signals()
to return a list of Signal objects (buy/sell).

Input DataFrame columns expected: date, Code, Close (QuantNodes convention).
Output: OrdersResult containing buy/sell signals at MA/RSI crossover points.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd

from QuantNodes.backtest.strategy_node import Order, OrdersResult, Signal, StrategyNode

logger = logging.getLogger(__name__)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize incoming DataFrame to QuantNodes convention (date, Code, Close)."""
    df = df.copy()
    col_map = {"date": "date", "datetime": "date", "ts_code": "Code", "code": "Code", "close": "Close"}
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    return df


def _make_orders(signals: List[Signal]) -> OrdersResult:
    """Convert signals to OrdersResult with corresponding orders.

    Always converts date to ISO string to ensure compatibility with broker
    date matching in both Path A (direct) and Path B (sandbox) execution paths.
    """
    result = OrdersResult()
    result.signals = signals
    for i, sig in enumerate(signals):
        order = Order(
            code=sig.code,
            size=1.0 if sig.signal_type == "buy" else -1.0,
            limit_price=sig.price,
            order_id=f"order_{i}",
            create_date=str(sig.date),
        )
        result.orders.append(order)
    return result


class MACrossStrategyNode(StrategyNode):
    """双均线交叉策略 (ma_cross)。"""

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "MACrossStrategy", config=config, **kwargs)
        self._fast = int(self.config.get("fast", 5))
        self._slow = int(self.config.get("slow", 20))

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)
        df["ma_fast"] = df["Close"].rolling(self._fast).mean()
        df["ma_slow"] = df["Close"].rolling(self._slow).mean()
        df["signal"] = 0
        df.loc[df["ma_fast"] > df["ma_slow"], "signal"] = 1
        df.loc[df["ma_fast"] <= df["ma_slow"], "signal"] = -1
        df["signal_diff"] = df["signal"].diff()

        signals = []
        codes = df["Code"].unique() if "Code" in df.columns else [None]
        for code in codes:
            sub = df[df["Code"] == code] if code is not None else df
            for _, row in sub.iterrows():
                if pd.notna(row.get("signal_diff")) and row["signal_diff"] != 0:
                    signals.append(Signal(
                        code=code or "DEFAULT",
                        signal_type="buy" if row["signal"] == 1 else "sell",
                        strength=1.0,
                        price=row.get("Close"),
                        date=row.get("date", ""),
                    ))
        return signals


class RSIStrategyNode(StrategyNode):
    """RSI 均值回归策略 (rsi)。"""

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "RSIStrategy", config=config, **kwargs)
        self._period = int(self.config.get("period", 14))
        self._oversold = float(self.config.get("oversold", 30))
        self._overbought = float(self.config.get("overbought", 70))

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(self._period).mean()
        loss = (-delta.clip(upper=0)).rolling(self._period).mean()
        rs = gain / loss.replace(0, 1e-10)
        df["rsi"] = 100 - 100 / (1 + rs)
        df["state"] = 0
        df.loc[df["rsi"] < self._oversold, "state"] = 1  # oversold → buy
        df.loc[df["rsi"] > self._overbought, "state"] = -1  # overbought → sell
        df["state_diff"] = df["state"].diff()

        signals = []
        codes = df["Code"].unique() if "Code" in df.columns else [None]
        for code in codes:
            sub = df[df["Code"] == code] if code is not None else df
            for _, row in sub.iterrows():
                if pd.notna(row.get("state_diff")) and row["state_diff"] != 0:
                    signals.append(Signal(
                        code=code or "DEFAULT",
                        signal_type="buy" if row["state"] == 1 else "sell",
                        strength=1.0,
                        price=row.get("Close"),
                        date=row.get("date", ""),
                    ))
        return signals


class MomentumStrategyNode(StrategyNode):
    """时序动量策略 (momentum)。"""

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "MomentumStrategy", config=config, **kwargs)
        self._period = int(self.config.get("period", 60))
        self._threshold = float(self.config.get("threshold", 0.05))

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)
        df["return"] = df["Close"].pct_change(self._period)

        signals = []
        codes = df["Code"].unique() if "Code" in df.columns else [None]
        for code in codes:
            sub = df[df["Code"] == code] if code is not None else df
            sub = sub.dropna(subset=["return"])
            prev_in = False
            for _, row in sub.iterrows():
                ret = row["return"]
                in_pos = ret > self._threshold
                if in_pos != prev_in:
                    signals.append(Signal(
                        code=code or "DEFAULT",
                        signal_type="buy" if in_pos else "sell",
                        strength=min(abs(ret) / self._threshold, 2.0),
                        price=row.get("Close"),
                        date=row.get("date", ""),
                    ))
                    prev_in = in_pos
        return signals


class VolatilityStrategyNode(StrategyNode):
    """波动率突破策略 (volatility)。"""

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "VolatilityStrategy", config=config, **kwargs)
        self._period = int(self.config.get("period", 20))
        self._entry_std = float(self.config.get("entry_std", 1.0))

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)
        df["ma"] = df["Close"].rolling(self._period).mean()
        df["std"] = df["Close"].rolling(self._period).std()
        df["upper"] = df["ma"] + self._entry_std * df["std"]
        df["lower"] = df["ma"] - self._entry_std * df["std"]
        df["signal"] = 0
        df.loc[df["Close"] > df["upper"], "signal"] = 1
        df.loc[df["Close"] < df["lower"], "signal"] = -1
        df["signal_diff"] = df["signal"].diff()

        signals = []
        codes = df["Code"].unique() if "Code" in df.columns else [None]
        for code in codes:
            sub = df[df["Code"] == code] if code is not None else df
            for _, row in sub.iterrows():
                if pd.notna(row.get("signal_diff")) and row["signal_diff"] != 0:
                    signals.append(Signal(
                        code=code or "DEFAULT",
                        signal_type="buy" if row["signal"] == 1 else "sell",
                        strength=1.0,
                        price=row.get("Close"),
                        date=row.get("date", ""),
                    ))
        return signals


class FactorRankStrategyNode(StrategyNode):
    """因子排名策略 (factor_rank)。

    注：单标的回测时此策略退化为简单的 0 持仓；
    多标的场景下按因子值排名买入/卖出。
    """

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "FactorRankStrategy", config=config, **kwargs)
        self._period = int(self.config.get("period", 20))
        self._factor_col = self.config.get("factor_col", "Close")

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty or "Code" not in input_data.columns:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)

        # Compute factor: rolling N-day return (cross-sectional momentum)
        df["_factor_ret"] = df.groupby("Code")["Close"].pct_change(self._period)

        signals = []
        for date, group in df.groupby("date"):
            if len(group) < 2:
                continue
            ranked = group["_factor_ret"].rank(pct=True, na_option="bottom")
            top = ranked[ranked > 0.8].index
            bottom = ranked[ranked < 0.2].index
            for idx in top:
                if pd.notna(group.loc[idx, "_factor_ret"]):
                    signals.append(Signal(
                        code=group.loc[idx, "Code"],
                        signal_type="buy",
                        strength=1.0,
                        price=group.loc[idx, "Close"],
                        date=str(date),
                    ))
            for idx in bottom:
                if pd.notna(group.loc[idx, "_factor_ret"]):
                    signals.append(Signal(
                        code=group.loc[idx, "Code"],
                        signal_type="sell",
                        strength=1.0,
                        price=group.loc[idx, "Close"],
                        date=str(date),
                    ))
        return signals


class SignalCompositeStrategyNode(StrategyNode):
    """多信号加权组合策略 (signal_composite)。"""

    def __init__(self, name: str = None, config: Dict[str, Any] = None, **kwargs):
        super().__init__(name=name or "SignalCompositeStrategy", config=config, **kwargs)
        self._weights = self.config.get("weights", {"ma": 0.5, "momentum": 0.5})
        self._fast = int(self.config.get("fast", 10))
        self._slow = int(self.config.get("slow", 30))
        self._momentum_period = int(self.config.get("momentum_period", 60))

    def _generate_signals(self, input_data: pd.DataFrame, **kwargs) -> List[Signal]:
        if input_data is None or input_data.empty:
            return []
        df = _normalize_columns(input_data).sort_values("date").reset_index(drop=True)

        df["ma_fast"] = df["Close"].rolling(self._fast).mean()
        df["ma_slow"] = df["Close"].rolling(self._slow).mean()
        df["ma_signal"] = (df["ma_fast"] - df["ma_slow"]) / df["ma_slow"]

        df["momentum"] = df["Close"].pct_change(self._momentum_period)

        df["composite"] = (
            self._weights.get("ma", 0.5) * df["ma_signal"].fillna(0)
            + self._weights.get("momentum", 0.5) * df["momentum"].fillna(0)
        )
        df["state"] = 0
        df.loc[df["composite"] > 0, "state"] = 1
        df.loc[df["composite"] < 0, "state"] = -1
        df["state_diff"] = df["state"].diff()

        signals = []
        codes = df["Code"].unique() if "Code" in df.columns else [None]
        for code in codes:
            sub = df[df["Code"] == code] if code is not None else df
            for _, row in sub.iterrows():
                if pd.notna(row.get("state_diff")) and row["state_diff"] != 0:
                    signals.append(Signal(
                        code=code or "DEFAULT",
                        signal_type="buy" if row["state"] == 1 else "sell",
                        strength=1.0,
                        price=row.get("Close"),
                        date=row.get("date", ""),
                    ))
        return signals


# Signal type → StrategyNode class registry
SIGNAL_NODE_REGISTRY: dict[str, type[StrategyNode]] = {
    "ma_cross": MACrossStrategyNode,
    "rsi": RSIStrategyNode,
    "momentum": MomentumStrategyNode,
    "volatility": VolatilityStrategyNode,
    "factor_rank": FactorRankStrategyNode,
    "signal_composite": SignalCompositeStrategyNode,
}


def get_strategy_node(signal_type: str, config: dict | None = None) -> StrategyNode:
    """Factory: build a QuantNodes StrategyNode for the given signal type."""
    cls = SIGNAL_NODE_REGISTRY.get(signal_type)
    if cls is None:
        raise ValueError(f"Unknown signal_type: {signal_type}. Available: {list(SIGNAL_NODE_REGISTRY.keys())}")
    return cls(config=config or {})