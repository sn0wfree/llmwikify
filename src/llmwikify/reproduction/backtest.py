"""Backtest engine with dual-path support.

Path A (primary): pre-written GenericStrategy with parameterized signal types.
Path B (fallback): LLM-generated Python code executed in a constrained namespace.

Both paths return the same BacktestResult schema.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .schemas import BacktestResult

logger = logging.getLogger(__name__)

PREWRITTEN_SIGNALS = {
    "ma_cross",
    "rsi",
    "factor_rank",
    "volatility",
    "momentum",
    "signal_composite",
}


def run_backtest(
    strategy: str,
    data: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> BacktestResult:
    """Run a backtest with the given strategy.

    Args:
        strategy: Either a pre-written signal type name
            ("ma_cross", "rsi", "factor_rank", "volatility", "momentum", "signal_composite")
            or a Python code string for fallback path.
        data: OHLCV DataFrame (must have open, high, low, close, volume columns).
        config: Optional dict with keys:
            - signal_params: dict of signal parameters
            - position_pct: fraction of cash to deploy per trade (default 0.95)
            - initial_cash: starting cash (default 1,000,000)
            - commission: commission rate (default 0.001)

    Returns:
        BacktestResult with all metrics populated.
    """
    import backtrader as bt

    cfg = {
        "signal_params": {},
        "position_pct": 0.95,
        "initial_cash": 1_000_000.0,
        "commission": 0.001,
        **(config or {}),
    }

    if strategy in PREWRITTEN_SIGNALS:
        return _run_prewritten(strategy, data, cfg)
    else:
        return _run_codegen(strategy, data, cfg)


def _build_cerebro(strategy_cls, data: pd.DataFrame, cfg: dict[str, Any]):
    """Create and configure a Cerebro instance."""
    import backtrader as bt

    # backtrader's PandasData expects datetime in the index
    if "date" in data.columns and not isinstance(data.index, pd.DatetimeIndex):
        data = data.set_index("date")
    elif "datetime" in data.columns and not isinstance(data.index, pd.DatetimeIndex):
        data = data.set_index("datetime")

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **cfg.get("signal_params", {}))
    feed = bt.feeds.PandasData(dataname=data)
    cerebro.adddata(feed)
    cerebro.broker.setcash(cfg["initial_cash"])
    cerebro.broker.setcommission(commission=cfg["commission"])
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0, timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    return cerebro


def _extract_metrics(strat, analyzers) -> dict[str, Any]:
    """Extract standardized metrics from backtrader output."""
    try:
        sharpe_analysis = analyzers.sharpe.get_analysis()
        sharpe = sharpe_analysis.get("sharperatio")
        sharpe_val = 0.0 if sharpe is None else float(sharpe)
    except Exception:
        sharpe_val = 0.0

    try:
        dd_analysis = analyzers.drawdown.get_analysis()
        drawdown = float(dd_analysis.get("max", {}).get("drawdown", 0.0) or 0.0)
    except Exception:
        drawdown = 0.0

    try:
        ta_analysis = analyzers.trades.get_analysis()
        total_closed = ta_analysis.get("total", {}).get("closed", 0) or 0
        won = ta_analysis.get("won", {}).get("total", 0) or 0
        win_rate = (won / total_closed) if total_closed > 0 else 0.0
    except Exception:
        total_closed = 0
        win_rate = 0.0

    return {
        "sharpe_ratio": sharpe_val,
        "max_drawdown": drawdown,
        "win_rate": win_rate,
        "trades_count": int(total_closed),
    }


def _run_prewritten(signal_type: str, data: pd.DataFrame, cfg: dict[str, Any]) -> BacktestResult:
    """Path A: use pre-written GenericStrategy."""
    import backtrader as bt

    signal_params = cfg.get("signal_params", {})
    strategy_cls = _make_strategy_class(signal_type, signal_params)

    try:
        cerebro = _build_cerebro(strategy_cls, data, cfg)
        initial_cash = cfg["initial_cash"]
        results = cerebro.run()
        strat = results[0]
        analyzers = strat.analyzers

        final_cash = cerebro.broker.getvalue()
        total_return = (final_cash - initial_cash) / initial_cash
        metrics = _extract_metrics(strat, analyzers)

        return BacktestResult(
            status="success",
            error=None,
            statistics=metrics,
            trades=strat.trades_list,
            final_cash=final_cash,
            total_return=total_return,
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            signal_type=signal_type,
            params=cfg,
        )
    except Exception as e:
        logger.exception("Pre-written backtest failed")
        return BacktestResult(
            status="error",
            error=str(e),
            signal_type=signal_type,
            params=cfg,
        )


def _make_strategy_class(signal_type: str, signal_params: dict[str, Any]):
    """Build a strategy class that uses the given signal type with params."""
    import backtrader as bt

    defaults = _signal_defaults(signal_type)
    merged = {**defaults, **signal_params}

    class GenericStrategy(bt.Strategy):
        params = tuple((k, v) for k, v in merged.items())
        params = params + (("position_pct", 0.95),)

        def __init__(self):
            self.order = None
            self.trades_list = []
            self.signal_line = _make_signal_line(signal_type, self.data, self.params)

        def notify_order(self, order):
            if order.status in [order.Completed, order.Canceled, order.Margin]:
                self.order = None

        def notify_trade(self, trade):
            if trade.isclosed:
                self.trades_list.append({
                    "ref": trade.ref,
                    "size": trade.size,
                    "price": trade.price,
                    "pnl": trade.pnl,
                    "pnlcomm": trade.pnlcomm,
                })

        def next(self):
            if self.order:
                return
            signal = self.signal_line[0]
            if signal > 0 and not self.position:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
            elif signal < 0 and self.position:
                self.order = self.close()

    GenericStrategy.__name__ = f"GenericStrategy_{signal_type}"
    return GenericStrategy


def _signal_defaults(signal_type: str) -> dict[str, Any]:
    """Default parameters for each signal type."""
    return {
        "ma_cross": {"fast": 5, "slow": 20},
        "rsi": {"period": 14},
        "momentum": {"period": 60},
        "volatility": {"period": 20},
        "factor_rank": {"period": 20},
        "signal_composite": {"fast": 10, "slow": 30, "momentum_period": 60},
    }.get(signal_type, {})


def _make_signal_line(signal_type: str, data, params):
    """Construct the indicator line for a given signal type with given params."""
    import backtrader as bt

    if signal_type == "ma_cross":
        fast_p = int(getattr(params, "fast", 5))
        slow_p = int(getattr(params, "slow", 20))
        return bt.indicators.DivByZero(
            bt.indicators.SMA(data.close, period=fast_p)
            - bt.indicators.SMA(data.close, period=slow_p),
            bt.indicators.SMA(data.close, period=slow_p),
        )
    elif signal_type == "rsi":
        period = int(getattr(params, "period", 14))
        return (50.0 - bt.indicators.RSI(data.close, period=period)) / 50.0
    elif signal_type == "momentum":
        period = int(getattr(params, "period", 60))
        return bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=period),
            bt.indicators.SMA(data.close, period=period),
        )
    elif signal_type == "volatility":
        period = int(getattr(params, "period", 20))
        return bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=period),
            bt.indicators.StandardDeviation(data.close, period=period),
        )
    elif signal_type == "factor_rank":
        period = int(getattr(params, "period", 20))
        return bt.indicators.PercentRank(data.close, period=period) - 0.5
    elif signal_type == "signal_composite":
        fast_p = int(getattr(params, "fast", 10))
        slow_p = int(getattr(params, "slow", 30))
        mom_p = int(getattr(params, "momentum_period", 60))
        ma = bt.indicators.DivByZero(
            bt.indicators.SMA(data.close, period=fast_p)
            - bt.indicators.SMA(data.close, period=slow_p),
            bt.indicators.SMA(data.close, period=slow_p),
        )
        mom = bt.indicators.DivByZero(
            data.close - bt.indicators.SMA(data.close, period=mom_p),
            bt.indicators.SMA(data.close, period=mom_p),
        )
        return (ma + mom) / 2
    else:
        return bt.indicators.Constant(0)


def _run_codegen(code: str, data: pd.DataFrame, cfg: dict[str, Any]) -> BacktestResult:
    """Path B: execute LLM-generated code in a constrained namespace."""
    import backtrader as bt

    namespace = {
        "bt": bt,
        "pd": pd,
        "data": data,  # pre-inject; user's `data = pd.read_csv(...)` may rebind locally
    }
    try:
        compiled = compile(code, "<llm_strategy>", "exec")
        exec(compiled, namespace)
        # After exec, restore the canonical data binding so framework code sees the real DataFrame
        namespace["data"] = data

        cerebro_obj = namespace.get("cerebro")
        if cerebro_obj is None:
            return BacktestResult(
                status="error",
                error="Generated code must define a 'cerebro' variable",
                signal_type="codegen",
                params=cfg,
            )

        # Check if the code already ran cerebro (callable already exhausted)
        already_run = hasattr(cerebro_obj, "_runonce") or getattr(cerebro_obj, "_strats", None) is not None and not cerebro_obj._strats
        if already_run:
            # Code already ran - try to get results from namespace
            results = namespace.get("results") or namespace.get("strats")
            if not results:
                return BacktestResult(
                    status="error",
                    error="cerebro.run() was called inside generated code but no results exposed",
                    signal_type="codegen",
                    params=cfg,
                )
        else:
            results = cerebro_obj.run()

        if not results:
            return BacktestResult(
                status="error",
                error="Backtest produced no results",
                signal_type="codegen",
                params=cfg,
            )

        strat = results[0]
        analyzers = strat.analyzers
        initial_cash = cfg["initial_cash"]
        final_cash = cerebro_obj.broker.getvalue()
        total_return = (final_cash - initial_cash) / initial_cash
        metrics = _extract_metrics(strat, analyzers)

        return BacktestResult(
            status="success",
            error=None,
            statistics=metrics,
            trades=getattr(strat, "trades_list", []),
            final_cash=final_cash,
            total_return=total_return,
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            signal_type="codegen",
            params=cfg,
        )
    except Exception as e:
        logger.exception("Code-gen backtest failed")
        return BacktestResult(
            status="error",
            error=str(e),
            signal_type="codegen",
            params=cfg,
        )