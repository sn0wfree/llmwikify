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

from .metrics import compute_metrics_from_trades
from .schemas import BacktestResult
from .strategies import SIGNAL_NODE_REGISTRY, get_strategy_node

logger = logging.getLogger(__name__)

THINKING_BLOCK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


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
        data: OHLCV DataFrame. Will be normalized to QuantNodes convention (date, Code, Close).
        config: Optional dict with keys:
            - signal_params: dict of signal parameters
            - initial_cash: starting cash (default 1,000,000)
            - commission: commission rate (default 0.001)
            - code: ts_code to assign to "Code" column (default "DEFAULT")
    """
    cfg = {
        "signal_params": {},
        "initial_cash": 1_000_000.0,
        "commission": 0.001,
        **(config or {}),
    }

    if strategy in SIGNAL_NODE_REGISTRY:
        return _run_prewritten(strategy, data, cfg)
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
        )
    except Exception as e:
        logger.exception("Code-gen backtest failed")
        return BacktestResult(
            status="error",
            error=str(e),
            signal_type="codegen",
            params=cfg,
        )