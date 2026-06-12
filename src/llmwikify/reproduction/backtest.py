"""Backtest engine — thin adapter over QuantNodes.

Path A (primary): pre-written StrategyNode with parameterized signal types.
Path B (fallback): LLM-generated Python code executed via QuantNodes sandbox.

Both paths return the same BacktestResult schema.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from .config import config
from .metrics import compute_metrics_from_trades, compute_monthly_returns
from .schemas import BacktestResult
from .strategies import SIGNAL_NODE_REGISTRY, get_strategy_node

logger = logging.getLogger(__name__)

THINKING_BLOCK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def run_backtest(
    strategy: str,
    data: pd.DataFrame,
    backtest_config: dict[str, Any] | None = None,
) -> BacktestResult:
    """Run a backtest with the given strategy.

    Args:
        strategy: Either a pre-written signal type name
            ("ma_cross", "rsi", "factor_rank", "volatility", "momentum", "signal_composite")
            or a Python code string for fallback path.
        data: OHLCV DataFrame. Will be normalized to QuantNodes convention (date, Code, Close).
        backtest_config: Optional dict with keys:
            - signal_params: dict of signal parameters
            - initial_cash: starting cash (default from config)
            - commission: commission rate (default from config)
            - code: ts_code to assign to "Code" column (default "DEFAULT")
    """
    # Get defaults from config
    default_initial_cash = config.get("backtest.initial_cash", 1_000_000.0)
    default_commission = config.get("backtest.commission", 0.001)

    cfg = {
        "signal_params": {},
        "initial_cash": default_initial_cash,
        "commission": default_commission,
        **(backtest_config or {}),
    }

    if strategy in SIGNAL_NODE_REGISTRY:
        return _run_prewritten(strategy, data, cfg)
    if strategy == "unknown" or strategy == "codegen":
        return BacktestResult(
            status="error",
            error=f"Cannot run backtest for signal_type='{strategy}'. "
                  "Provide a valid signal_type or LLM-generated code.",
            signal_type=strategy,
            params=cfg,
        )
    return _run_codegen(strategy, data, cfg)


def _prepare_data(data: pd.DataFrame, code: str) -> pd.DataFrame:
    """Normalize incoming DataFrame to QuantNodes convention (date, Code, Close)."""
    df = data.copy()
    if not isinstance(df.index, pd.DatetimeIndex) and "date" in df.columns:
        df = df.set_index("date")
    elif not isinstance(df.index, pd.DatetimeIndex) and "datetime" in df.columns:
        df = df.set_index("datetime")
    df = df.reset_index()
    df.columns = [str(c) for c in df.columns]

    rename: dict[str, str] = {}
    col_lower = {c.lower(): c for c in df.columns}

    if "date" not in df.columns:
        for cand in ["date", "datetime", "Date"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "date"
                break
    if "Close" not in df.columns:
        for cand in ["close", "Close"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "Close"
                break
    if "Open" not in df.columns:
        for cand in ["open", "Open"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "Open"
                break
    if "High" not in df.columns:
        for cand in ["high", "High"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "High"
                break
    if "Low" not in df.columns:
        for cand in ["low", "Low"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "Low"
                break
    if "Volume" not in df.columns:
        for cand in ["volume", "Volume", "vol"]:
            if cand in col_lower:
                rename[col_lower[cand]] = "Volume"
                break
    if rename:
        df = df.rename(columns=rename)

    if "date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "date"})
    if "Code" not in df.columns:
        # Use existing ts_code / code column if present, else default code
        for cand in ["ts_code", "code", "Code"]:
            if cand in df.columns:
                df["Code"] = df[cand].astype(str)
                break
        else:
            df["Code"] = code
    else:
        df["Code"] = df["Code"].astype(str)
    if "Close" not in df.columns or df["Close"].isna().all():
        raise ValueError(f"DataFrame must have 'close' column. Got: {data.columns.tolist()}")

    # Normalize date to ISO string for consistent matching across all paths
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    return df.sort_values("date").reset_index(drop=True)


def _reconstruct_equity_curve(
    trades: list[Any],
    data: pd.DataFrame,
    initial_cash: float,
) -> list[dict[str, Any]]:
    """Reconstruct daily equity time series from trades and price data.

    Iterates over each bar in ``data``, tracks open position, and computes
    equity = cash + position * close_price at each bar.
    """
    if data.empty:
        return []

    dates = data["date"].tolist()
    closes = data["Close"].tolist()

    cash = initial_cash
    position = 0.0
    equity_list: list[dict[str, Any]] = []

    # Index trades by date for O(1) lookup
    trades_by_date: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        t_date = ""
        if isinstance(t, dict):
            t_date = str(t.get("date", t.get("create_date", "")))[:10]
        elif hasattr(t, "date"):
            t_date = str(getattr(t, "date", ""))[:10]
        if t_date:
            trades_by_date.setdefault(t_date, []).append(t)

    for i, (date_str, close) in enumerate(zip(dates, closes)):
        # Process trades for this bar
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


def _run_prewritten(signal_type: str, data: pd.DataFrame, cfg: dict[str, Any]) -> BacktestResult:
    """Path A: pre-written QuantNodes StrategyNode."""
    from QuantNodes.backtest.broker_node import SimulatedBrokerNode

    try:
        df = _prepare_data(data, cfg.get("code", "DEFAULT"))
        strategy_node = get_strategy_node(signal_type, cfg.get("signal_params", {}))
        broker = SimulatedBrokerNode(config={
            "cash": cfg["initial_cash"],
            "commission": cfg["commission"],
            "trade_on_close": False,  # execute on next bar's Open for realistic pnls
        })

        orders_result = strategy_node.execute(df)
        trade_result = broker.execute((orders_result, df))

        trades_list = [t.__dict__ if hasattr(t, "__dict__") else t for t in trade_result.trades]
        final_cash = float(trade_result.cash)
        metrics = compute_metrics_from_trades(
            trades=trade_result.trades,
            initial_cash=cfg["initial_cash"],
            final_cash=final_cash,
        )
        equity_curve = _reconstruct_equity_curve(trades_list, df, cfg["initial_cash"])
        monthly_returns = compute_monthly_returns(equity_curve, trade_result.trades, cfg["initial_cash"])

        return BacktestResult(
            status="success",
            error=None,
            statistics=metrics,
            trades=trades_list,
            final_cash=final_cash,
            total_return=metrics["total_return"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            signal_type=signal_type,
            params=cfg,
            summary={
                "total_trades": len(trade_result.trades),
                "final_cash": final_cash,
                "total_commission": float(trade_result.commission),
                "strategy": strategy_node.__class__.__name__,
                "broker": broker.__class__.__name__,
                "data_rows": len(df),
            },
            config={
                "signal_type": signal_type,
                "signal_params": cfg.get("signal_params", {}),
                "initial_cash": cfg["initial_cash"],
                "commission": cfg["commission"],
            },
            security_status="n/a",
            nodes={
                "strategy": strategy_node.__class__.__name__,
                "broker": broker.__class__.__name__,
            },
            equity_curve=equity_curve,
            monthly_returns=monthly_returns,
        )
    except Exception as e:
        logger.exception("Pre-written backtest failed")
        return BacktestResult(
            status="error",
            error=str(e),
            signal_type=signal_type,
            params=cfg,
        )


def _strip_thinking(text: str) -> str:
    """Strip LLM thinking blocks."""
    text = THINKING_BLOCK_RE.sub("", text)
    return text.strip()


def _extract_code(text: str) -> str:
    """Strip thinking blocks + markdown fences; return raw Python."""
    text = _strip_thinking(text)
    m = CODE_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _run_codegen(code: str, data: pd.DataFrame, cfg: dict[str, Any]) -> BacktestResult:
    """Path B: execute LLM-generated code via QuantNodes sandbox + pipeline.

    The code is expected to define a StrategyNode instance named `strategy`,
    plus `quote_data` as a pandas DataFrame. QuantNodes runs the pipeline.
    """
    from QuantNodes.ai.sandbox import CodeSandbox
    from QuantNodes.backtest.broker_node import SimulatedBrokerNode
    from QuantNodes.backtest.strategy_node import StrategyNode

    try:
        clean_code = _extract_code(code)
        df = _prepare_data(data, cfg.get("code", "DEFAULT"))

        # QuantNodes sandbox doesn't auto-inject 'data'; embed the DataFrame
        # as a pd.DataFrame.from_records() call. Dates are kept as ISO strings
        # (sandbox can't import pd.Timestamp). The order.create_date will also
        # be a string in this path; we add a custom broker wrapper that matches
        # both string and Timestamp keys.
        df_records = df.to_dict(orient="records")

        wrapped_code = (
            clean_code.rstrip()
            + f"\nquote_data = pd.DataFrame.from_records({df_records!r})\n"
        )

        # Use sandbox with higher max_code_length for large DataFrames
        sandbox = CodeSandbox(max_code_length=500_000)
        validation = sandbox.validate(wrapped_code)
        if not validation.is_safe:
            return BacktestResult(
                status="error",
                error="; ".join(validation.errors),
                signal_type="codegen",
                params=cfg,
                security_status="unsafe",
            )

        context = {
            "pd": pd,
            "np": __import__("numpy"),
            "QuantNodes": __import__("QuantNodes"),
        }
        namespace = sandbox.validate_and_execute(wrapped_code, context)

        strategy = None
        broker = None
        quote_data = None
        for name, obj in namespace.items():
            if isinstance(obj, StrategyNode):
                strategy = obj
            elif isinstance(obj, SimulatedBrokerNode):
                broker = obj
        quote_data = namespace.get("quote_data")
        if quote_data is None:
            quote_data = namespace.get("data")

        if strategy is None:
            return BacktestResult(
                status="error",
                error="No StrategyNode found. Code must define 'strategy' variable.",
                signal_type="codegen",
                params=cfg,
            )
        if quote_data is None:
            return BacktestResult(
                status="error",
                error="No quote_data found. Code must define 'quote_data' DataFrame.",
                signal_type="codegen",
                params=cfg,
            )
        if broker is None:
            broker = SimulatedBrokerNode(config={
                "cash": cfg["initial_cash"],
                "commission": cfg["commission"],
                "trade_on_close": False,  # execute on next bar's Open for realistic pnls
            })

        orders_result = strategy.execute(quote_data)
        trade_result = broker.execute((orders_result, quote_data))

        trades_list = trade_result.trades
        trades_serialized = [t.__dict__ for t in trades_list]
        final_cash = float(trade_result.cash)
        metrics = compute_metrics_from_trades(
            trades=trades_list,
            initial_cash=cfg["initial_cash"],
            final_cash=final_cash,
        )
        equity_curve = _reconstruct_equity_curve(trades_serialized, quote_data, cfg["initial_cash"])
        monthly_returns = compute_monthly_returns(equity_curve, trades_list, cfg["initial_cash"])

        return BacktestResult(
            status="success",
            error=None,
            statistics=metrics,
            trades=trades_serialized,
            final_cash=final_cash,
            total_return=metrics["total_return"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            signal_type="codegen",
            params=cfg,
            summary={
                "total_trades": len(trades_list),
                "final_cash": final_cash,
                "total_commission": float(trade_result.commission),
                "strategy": strategy.__class__.__name__,
                "broker": broker.__class__.__name__,
                "data_rows": len(quote_data),
            },
            config={
                "initial_cash": cfg["initial_cash"],
                "commission": cfg["commission"],
            },
            security_status="safe",
            nodes={
                "strategy": strategy.__class__.__name__,
                "broker": broker.__class__.__name__,
            },
            equity_curve=equity_curve,
            monthly_returns=monthly_returns,
        )
    except Exception as e:
        logger.exception("Code-gen backtest failed")
        return BacktestResult(
            status="error",
            error=str(e),
            signal_type="codegen",
            params=cfg,
        )