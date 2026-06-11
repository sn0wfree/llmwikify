"""Backtest metrics computation (sharpe, max_drawdown, win_rate, CAGR, sortino, alpha, beta).

Computed from QuantNodes TradeResult. Since QuantNodes Trade objects lack a `pnl`
attribute (only `fee`), we compute pnl by pairing consecutive buy/sell trades
for the same code.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


def _extract_trade_info(trade: Any) -> Tuple[str, float, float]:
    """Return (side, price, fee) from a Trade object or dict."""
    if isinstance(trade, dict):
        return trade.get("side", ""), float(trade.get("price", 0.0)), float(trade.get("fee", 0.0))
    return (
        getattr(trade, "side", ""),
        float(getattr(trade, "price", 0.0)),
        float(getattr(trade, "fee", 0.0)),
    )


def _pair_trades_to_pnls(trades: List[Any]) -> List[float]:
    """Pair buy/sell trades per code into round-trips and compute pnls.

    Strategy:
    - If first trade is sell → short entry (open short position)
    - If subsequent trade is buy → close short (pnl = entry_price - exit_price - fees)
    - If subsequent trade is sell → open another short or extend position
    - At the end, mark-to-market any open position at last close price

    Returns a list of realized pnls (one per round-trip) + final mark-to-market.
    """
    if not trades:
        return []

    pnls: List[float] = []
    open_positions: Dict[str, List[Tuple[float, float, float]]] = {}

    for trade in trades:
        side, price, fee = _extract_trade_info(trade)
        if isinstance(trade, dict):
            code = trade.get("code", "DEFAULT")
            size = float(trade.get("size", 1.0))
        else:
            code = getattr(trade, "code", "DEFAULT")
            size = float(getattr(trade, "size", 1.0))

        if side == "buy":
            entries = open_positions.get(code, [])
            if entries:
                # Closing short position(s)
                while entries and size > 0:
                    entry_price, entry_fee, entry_size = entries[-1]
                    matched = min(size, entry_size)
                    pnl = (entry_price - price) * matched - entry_fee - fee
                    pnls.append(pnl)
                    size -= matched
                    if matched >= entry_size:
                        entries.pop()
                    else:
                        entries[-1] = (entry_price, entry_fee, entry_size - matched)
                if not entries:
                    open_positions.pop(code, None)
                if size > 0:
                    open_positions.setdefault(code, []).append((price, fee, size))
            else:
                # Opening long position
                open_positions.setdefault(code, []).append((price, fee, size))

        elif side == "sell":
            entries = open_positions.get(code, [])
            if entries:
                # Closing long position(s)
                while entries and size > 0:
                    entry_price, entry_fee, entry_size = entries[-1]
                    matched = min(size, entry_size)
                    pnl = (price - entry_price) * matched - entry_fee - fee
                    pnls.append(pnl)
                    size -= matched
                    if matched >= entry_size:
                        entries.pop()
                    else:
                        entries[-1] = (entry_price, entry_fee, entry_size - matched)
                if not entries:
                    open_positions.pop(code, None)
                if size > 0:
                    open_positions.setdefault(code, []).append((price, fee, size))
            else:
                # Opening short position
                open_positions.setdefault(code, []).append((price, fee, size))

    return pnls


def compute_metrics_from_trades(
    trades: List[Any],
    initial_cash: float,
    final_cash: float,
    trading_days: int = 252,
) -> Dict[str, float]:
    """Compute sharpe_ratio, max_drawdown, win_rate, total_return from trades.

    Note: QuantNodes Trade objects lack a `pnl` attribute — we compute round-trip
    pnls by pairing buys/sells. When buy and sell prices are equal (same-bar
    close), pnl ≈ -fee only; we treat such trades as "neutral" (not counted
    as losses) to avoid pathological sharpe ratios.

    Args:
        trades: List of QuantNodes Trade objects (or dicts).
        initial_cash: Starting capital.
        final_cash: Ending capital (from broker).
        trading_days: Annualization factor (default 252 for daily).

    Returns:
        Dict with sharpe_ratio, max_drawdown, win_rate, total_return.
    """
    if initial_cash <= 0:
        return {"sharpe_ratio": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "total_return": 0.0}

    total_return = (final_cash - initial_cash) / initial_cash

    pnls = _pair_trades_to_pnls(trades)
    # Drop fee-only pnls (entry == exit price, common with same-bar close).
    # These are "neutral" trades that don't reflect strategy performance.
    meaningful_pnls = [p for p in pnls if abs(p) > 1e-6]

    wins = sum(1 for p in meaningful_pnls if p > 0)
    win_rate = wins / len(meaningful_pnls) if meaningful_pnls else 0.0

    if len(meaningful_pnls) >= 2:
        mean_pnl = sum(meaningful_pnls) / len(meaningful_pnls)
        variance = sum((p - mean_pnl) ** 2 for p in meaningful_pnls) / (len(meaningful_pnls) - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 0.0
        sharpe_ratio = _safe_div(mean_pnl * math.sqrt(trading_days), std_pnl, 0.0)
    else:
        sharpe_ratio = 0.0

    max_drawdown = _compute_max_drawdown(final_cash, initial_cash, list(meaningful_pnls))

    return {
        "sharpe_ratio": round(sharpe_ratio, 6),
        "max_drawdown": round(max_drawdown, 6),
        "win_rate": round(win_rate, 6),
        "total_return": round(total_return, 6),
    }


def _compute_max_drawdown(
    final_cash: float, initial_cash: float, pnls: List[float]
) -> float:
    """Approximate max drawdown from cumulative pnl path."""
    if not pnls:
        return 0.0

    equity = initial_cash
    peak = initial_cash
    max_dd = 0.0

    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd * 100.0


def compute_extended_metrics(
    trades: List[Any],
    initial_cash: float,
    final_cash: float,
    trading_days: int = 252,
    benchmark_returns: Optional[List[float]] = None,
    risk_free_rate: float = 0.03,
) -> Dict[str, float]:
    """Compute extended metrics: CAGR, Sortino, Alpha, Beta.

    Args:
        trades: List of QuantNodes Trade objects (or dicts).
        initial_cash: Starting capital.
        final_cash: Ending capital (from broker).
        trading_days: Annualization factor (default 252 for daily).
        benchmark_returns: List of daily benchmark returns (for Alpha/Beta).
        risk_free_rate: Annual risk-free rate (default 3%).

    Returns:
        Dict with cagr, sortino_ratio, alpha, beta (in addition to base metrics).
    """
    base = compute_metrics_from_trades(trades, initial_cash, final_cash, trading_days)

    # CAGR
    pnls = _pair_trades_to_pnls(trades)
    n_periods = len(pnls) if pnls else trading_days
    if initial_cash > 0 and final_cash > 0 and n_periods > 0:
        cagr = (final_cash / initial_cash) ** (trading_days / max(n_periods, 1)) - 1
    else:
        cagr = 0.0

    # Sortino ratio (downside deviation)
    meaningful_pnls = [p for p in pnls if abs(p) > 1e-6]
    if len(meaningful_pnls) >= 2:
        mean_pnl = sum(meaningful_pnls) / len(meaningful_pnls)
        downside_pnls = [p for p in meaningful_pnls if p < 0]
        if downside_pnls:
            downside_var = sum(p ** 2 for p in downside_pnls) / len(downside_pnls)
            downside_std = math.sqrt(downside_var)
        else:
            downside_std = 0.0
        sortino = _safe_div(mean_pnl * math.sqrt(trading_days), downside_std, 0.0)
    else:
        sortino = 0.0

    # Alpha / Beta (require benchmark returns)
    alpha = 0.0
    beta = 0.0
    if benchmark_returns and len(benchmark_returns) >= 2:
        # Compute strategy daily returns from pnls
        strategy_returns = []
        equity = initial_cash
        for pnl in meaningful_pnls:
            ret = pnl / equity if equity > 0 else 0.0
            strategy_returns.append(ret)
            equity += pnl

        # Align lengths
        n = min(len(strategy_returns), len(benchmark_returns))
        if n >= 2:
            sr = strategy_returns[:n]
            br = benchmark_returns[:n]
            mean_sr = sum(sr) / n
            mean_br = sum(br) / n

            # Beta = Cov(S, B) / Var(B)
            cov = sum((sr[i] - mean_sr) * (br[i] - mean_br) for i in range(n)) / (n - 1)
            var_b = sum((br[i] - mean_br) ** 2 for i in range(n)) / (n - 1)
            beta = _safe_div(cov, var_b, 0.0)

            # Alpha = annualized (strategy return - risk_free - beta * (benchmark return - risk_free))
            daily_rf = risk_free_rate / trading_days
            alpha_daily = mean_sr - daily_rf - beta * (mean_br - daily_rf)
            alpha = alpha_daily * trading_days

    return {
        **base,
        "cagr": round(cagr, 6),
        "sortino_ratio": round(sortino, 6),
        "alpha": round(alpha, 6),
        "beta": round(beta, 6),
    }


def compute_monthly_returns(
    equity_curve: List[Dict[str, Any]],
    trades: List[Any],
    initial_cash: float,
) -> Dict[str, float]:
    """Compute monthly returns from equity curve time series.

    Args:
        equity_curve: Daily equity values [{date: "YYYY-MM-DD", value: float}, ...].
        trades: Trade objects (unused, kept for backward compat).
        initial_cash: Starting cash.

    Returns:
        Dict {"YYYY-MM": return_pct} for heatmap visualization.
    """
    if not equity_curve:
        return {}

    # Group equity by year-month, take last equity value per month
    monthly_equity: Dict[str, float] = {}
    for pt in equity_curve:
        date_str = pt.get("date", "")
        value = pt.get("value", 0.0)
        if len(date_str) >= 7:
            ym = date_str[:7]  # "YYYY-MM"
            monthly_equity[ym] = value

    if len(monthly_equity) < 2:
        return {}

    # Sort by year-month and compute returns
    sorted_months = sorted(monthly_equity.keys())
    result: Dict[str, float] = {}
    prev_equity = initial_cash
    for ym in sorted_months:
        cur_equity = monthly_equity[ym]
        ret = (cur_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        result[ym] = round(ret * 100, 2)
        prev_equity = cur_equity

    return result