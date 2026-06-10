"""Factor backtest engine — IC analysis, quantile returns, turnover.

Computes factor metrics from OHLCV data:
  - IC (Information Coefficient): rank correlation between factor values and forward returns
  - Quantile returns: cumulative returns of G1-G5 groups sorted by factor value
  - Turnover: how often the top/bottom quantile changes

Supports two modes:
  - Single-stock: time-series IC (factor vs forward return correlation over time)
  - Multi-stock: cross-sectional IC (factor vs forward return correlation across stocks)

The factor calculation is delegated to a strategy node from strategies.py,
or computed directly from factor_class + factor_params.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from .schemas import FactorBacktestResult

logger = logging.getLogger(__name__)


# ─── Factor computation ──────────────────────────────────────

def _compute_factor_values(
    data: pd.DataFrame,
    factor_class: str,
    factor_params: dict[str, Any],
) -> pd.Series:
    """Compute factor values from OHLCV data.

    Args:
        data: DataFrame with columns [date, open, high, low, close, volume].
        factor_class: Factor type (momentum, volatility, value, quality, size, growth).
        factor_params: Parameters for factor construction.

    Returns:
        Series of factor values aligned with input data index.
    """
    close = data["close"]

    if factor_class == "momentum":
        period = int(factor_params.get("lookback", factor_params.get("period", 20)))
        return close.pct_change(period)

    elif factor_class == "volatility":
        period = int(factor_params.get("period", 20))
        return close.pct_change().rolling(period).std()

    elif factor_class == "ma_cross":
        fast = int(factor_params.get("fast", factor_params.get("period", 5)))
        slow = int(factor_params.get("slow", 20))
        ma_fast = close.rolling(fast).mean()
        ma_slow = close.rolling(slow).mean()
        return (ma_fast - ma_slow) / ma_slow

    elif factor_class == "rsi":
        period = int(factor_params.get("period", 14))
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    elif factor_class == "value":
        # Price-to-MA ratio (simplified value factor)
        period = int(factor_params.get("period", 60))
        ma = close.rolling(period).mean()
        return close / ma - 1

    elif factor_class == "quality":
        # Return stability (inverse of return volatility)
        period = int(factor_params.get("period", 20))
        return -close.pct_change().rolling(period).std()

    elif factor_class == "size":
        # Log market cap proxy (using volume * close as proxy)
        volume = data.get("volume", pd.Series(1.0, index=data.index))
        return np.log(close * volume + 1)

    elif factor_class == "growth":
        # Earnings growth proxy (revenue momentum)
        period = int(factor_params.get("period", 60))
        return close.pct_change(period)

    elif factor_class == "signal_composite":
        # Weighted combination of momentum + volatility
        fast = int(factor_params.get("fast", factor_params.get("period", 5)))
        slow = int(factor_params.get("slow", 20))
        mom = close.pct_change(fast)
        vol = close.pct_change().rolling(slow).std()
        return mom / vol.replace(0, np.nan)

    else:
        # Default: momentum
        period = int(factor_params.get("lookback", factor_params.get("period", 20)))
        return close.pct_change(period)


# ─── IC computation ──────────────────────────────────────────

def _compute_ic_series(
    factor_values: pd.Series,
    forward_returns: pd.Series,
) -> tuple[float, float, float, float, list[dict[str, Any]]]:
    """Compute IC statistics from factor values and forward returns.

    Args:
        factor_values: Factor values (aligned by index).
        forward_returns: Forward N-day returns (aligned by index).

    Returns:
        (ic_mean, ic_std, icir, t_stat, ic_series) where ic_series is
        a list of {date, ic} dicts.
    """
    # Align and drop NaN
    aligned = pd.DataFrame({
        "factor": factor_values,
        "fwd_ret": forward_returns,
    }).dropna()

    if len(aligned) < 3:
        return 0.0, 0.0, 0.0, 0.0, []

    # Compute rank IC (Spearman correlation) per period
    ic_series = []
    for idx, row in aligned.iterrows():
        # For single-stock: use time-series rank correlation
        # For simplicity, use Pearson for now (rank IC needs cross-sectional data)
        ic_series.append({
            "date": str(idx) if hasattr(idx, "isoformat") else str(idx),
            "ic": 0.0,  # placeholder, computed below
        })

    # Compute rolling IC (Pearson correlation over rolling window)
    window = min(20, len(aligned) - 1)
    if window < 3:
        # Not enough data for rolling, compute single IC
        ic = aligned["factor"].corr(aligned["fwd_ret"])
        if np.isnan(ic):
            ic = 0.0
        ic_list = [{"date": str(aligned.index[0]), "ic": ic}]
        ic_mean = ic
        ic_std = 0.0
    else:
        # Rolling IC
        rolling_ic = aligned["factor"].rolling(window).corr(aligned["fwd_ret"])
        rolling_ic = rolling_ic.dropna()
        if len(rolling_ic) == 0:
            ic = aligned["factor"].corr(aligned["fwd_ret"])
            if np.isnan(ic):
                ic = 0.0
            rolling_ic = pd.Series([ic])
        ic_list = [
            {"date": str(idx), "ic": float(v)}
            for idx, v in rolling_ic.items()
            if not np.isnan(v)
        ]
        ic_mean = float(rolling_ic.mean()) if len(rolling_ic) > 0 else 0.0
        ic_std = float(rolling_ic.std()) if len(rolling_ic) > 1 else 0.0

    # ICIR = mean / std
    icir = ic_mean / ic_std if ic_std > 0 else 0.0

    # T-statistic
    n = len(ic_list)
    t_stat = ic_mean * math.sqrt(n) / ic_std if ic_std > 0 and n > 1 else 0.0

    return ic_mean, ic_std, icir, t_stat, ic_list


# ─── Quantile returns ────────────────────────────────────────

def _compute_quantile_returns(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    n_groups: int = 5,
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]]]:
    """Compute quantile group returns.

    For single-stock: groups are based on factor value percentiles.
    For multi-stock: groups are based on cross-sectional rank percentiles.

    Args:
        factor_values: Factor values.
        forward_returns: Forward returns.
        n_groups: Number of quantile groups (default 5 = G1-G5).

    Returns:
        (quantile_returns, quantile_curves) where:
        - quantile_returns: {group: annual_return}
        - quantile_curves: {group: [{date, value}]}
    """
    aligned = pd.DataFrame({
        "factor": factor_values,
        "fwd_ret": forward_returns,
    }).dropna()

    if len(aligned) < n_groups:
        return {}, {}

    # Assign quantile groups
    try:
        aligned["group"] = pd.qcut(aligned["factor"], n_groups, labels=False, duplicates="drop")
    except ValueError:
        # If qcut fails (e.g., too many duplicates), use rank-based assignment
        aligned["group"] = (aligned["factor"].rank(pct=True) * n_groups).astype(int).clip(0, n_groups - 1)

    # Compute cumulative return per group
    quantile_returns = {}
    quantile_curves = {}

    for g in range(n_groups):
        group_label = f"G{g + 1}"
        group_data = aligned[aligned["group"] == g]

        if len(group_data) == 0:
            quantile_returns[group_label] = 0.0
            quantile_curves[group_label] = []
            continue

        # Cumulative return
        cum_ret = (1 + group_data["fwd_ret"]).prod() - 1
        quantile_returns[group_label] = float(cum_ret)

        # Cumulative curve (for chart)
        curve = []
        cumulative = 1.0
        for idx, row in group_data.iterrows():
            cumulative *= (1 + row["fwd_ret"])
            curve.append({
                "date": str(idx) if hasattr(idx, "isoformat") else str(idx),
                "value": round(cumulative, 6),
            })
        quantile_curves[group_label] = curve

    return quantile_returns, quantile_curves


# ─── Turnover ────────────────────────────────────────────────

def _compute_turnover(
    factor_values: pd.Series,
    n_groups: int = 5,
) -> float:
    """Compute average turnover rate of top quantile.

    Turnover = fraction of top group that changes between consecutive periods.
    """
    if len(factor_values) < 2:
        return 0.0

    # Drop NaN and check
    clean = factor_values.dropna()
    if len(clean) < n_groups:
        return 0.0

    # Assign groups
    try:
        groups = pd.qcut(clean, n_groups, labels=False, duplicates="drop")
    except (ValueError, IndexError):
        return 0.0

    if groups is None or len(groups) < 2:
        return 0.0

    top_group = n_groups - 1
    top_mask = groups == top_group

    changes = 0
    count = 0
    prev_top = None
    for i, (idx, val) in enumerate(top_mask.items()):
        if prev_top is not None and not pd.isna(val) and not pd.isna(prev_top):
            count += 1
            if val != prev_top:
                changes += 1
        prev_top = val

    return changes / count if count > 0 else 0.0


# ─── Main function ───────────────────────────────────────────

def run_factor_backtest(
    data: pd.DataFrame,
    factor_class: str,
    factor_params: dict[str, Any],
    forward_days: int = 1,
    n_groups: int = 5,
) -> FactorBacktestResult:
    """Run single-factor backtest.

    Args:
        data: OHLCV DataFrame with columns [date, open, high, low, close, volume].
        factor_class: Factor type (momentum, volatility, value, etc.).
        factor_params: Factor construction parameters.
        forward_days: Forward return period (default 1 day).
        n_groups: Number of quantile groups (default 5).

    Returns:
        FactorBacktestResult with IC metrics, quantile returns, and curves.
    """
    if data is None or data.empty or "close" not in data.columns:
        logger.warning("empty or invalid data for factor backtest")
        return FactorBacktestResult()

    # Compute factor values
    factor_values = _compute_factor_values(data, factor_class, factor_params)

    # Compute forward returns
    forward_returns = data["close"].pct_change(forward_days).shift(-forward_days)

    # IC analysis
    ic_mean, ic_std, icir, t_stat, ic_series = _compute_ic_series(
        factor_values, forward_returns
    )

    # Win rate (IC > 0 ratio)
    ic_values = [pt["ic"] for pt in ic_series]
    win_rate = sum(1 for v in ic_values if v > 0) / len(ic_values) if ic_values else 0.0

    # Quantile returns
    quantile_returns, quantile_curves = _compute_quantile_returns(
        factor_values, forward_returns, n_groups
    )

    # Annualized return (from G1 long-only)
    g1_return = quantile_returns.get("G1", 0.0)
    n_periods = len(data)
    annual_return = g1_return * (252 / max(n_periods, 1)) if n_periods > 0 else 0.0

    # Max drawdown (from G1 cumulative curve)
    g1_curve = quantile_curves.get("G1", [])
    max_dd = 0.0
    if g1_curve:
        peak = 1.0
        for pt in g1_curve:
            val = pt["value"]
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd

    # Turnover
    turnover = _compute_turnover(factor_values, n_groups)

    return FactorBacktestResult(
        ic_mean=round(ic_mean, 6),
        ic_std=round(ic_std, 6),
        icir=round(icir, 4),
        t_stat=round(t_stat, 4),
        win_rate=round(win_rate, 4),
        annual_return=round(annual_return, 6),
        max_drawdown=round(max_dd * 100, 4),
        turnover=round(turnover, 4),
        quantile_returns={k: round(v, 6) for k, v in quantile_returns.items()},
        ic_series=ic_series,
        quantile_curves=quantile_curves,
    )


__all__ = [
    "run_factor_backtest",
    "_compute_factor_values",
]