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

    elif factor_class == "formula":
        # LLM-generated code execution
        code = factor_params.get("code", "")
        if not code:
            logger.warning("factor_class='formula' but no code provided, falling back to momentum")
            period = int(factor_params.get("period", 20))
            return close.pct_change(period)
        return _compute_factor_from_code(data, code)

    else:
        # Default: momentum
        period = int(factor_params.get("lookback", factor_params.get("period", 20)))
        return close.pct_change(period)


def _compute_factor_from_code(data: pd.DataFrame, code: str) -> pd.Series:
    """Execute LLM-generated code to compute factor values.

    Args:
        data: DataFrame with columns [date, close, ...].
        code: Python code string defining compute_factor(df) function.

    Returns:
        Series of factor values.
    """
    from QuantNodes.ai.sandbox import CodeSandbox

    sandbox = CodeSandbox(max_code_length=500_000)
    validation = sandbox.validate(code)
    if not validation.is_safe:
        raise ValueError(f"Unsafe factor code: {validation.errors}")

    # Convert date to string for serialization, then parse back in code
    data_for_exec = data.copy()
    if "date" in data_for_exec.columns:
        data_for_exec["date"] = data_for_exec["date"].astype(str)

    # Inject data as a literal and call compute_factor
    data_records = data_for_exec.to_dict(orient="records")
    wrapped_code = (
        code.rstrip()
        + "\n_df = pd.DataFrame(_DATA_RECORDS)\n"
        + "_df['date'] = pd.to_datetime(_df['date'])\n"
        + "_result = compute_factor(_df)\n"
    )

    namespace = sandbox.validate_and_execute(
        wrapped_code,
        {"pd": pd, "np": __import__("numpy"), "_DATA_RECORDS": data_records},
    )
    result = namespace.get("_result")
    if result is None:
        raise ValueError("compute_factor() did not return a result")
    if isinstance(result, pd.DataFrame):
        result = result.iloc[:, 0]
    return result.astype(float)


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
    "run_factor_backtest_universe",
    "_compute_factor_values",
    "_compute_factor_matrix",
    "_compute_cross_section_ic",
    "_compute_cross_section_groups",
    "_compute_long_short",
    "generate_adj_dates",
]


# ════════════════════════════════════════════════════════════════
#  Cross-section (multi-stock universe) factor backtest
# ════════════════════════════════════════════════════════════════
#
# References:
#   - ~/Public/单因子回测/factor_performance.py
#   - QuantNodes/research/factor_test/nodes/{ic,group,long_short}_analyzer_node.py
#   - QuantNodes/research/factor_test/pipeline_runner.py
#
# Data shapes:
#   close_wide: pd.DataFrame indexed by date, columns are stock codes
#               (e.g. "000001.SZ", "600519.SH"). Each cell is close price.
#   factor_wide: same shape as close_wide, values are factor values.
#   return_wide: same shape, values are forward N-day returns.
#
# Pipeline:
#   close_wide → _compute_factor_matrix → factor_wide
#   close_wide → _compute_return_matrix → return_wide
#   (factor_wide, return_wide) → _compute_cross_section_ic → ic_result
#   (factor_wide, return_wide, adj_dates) → _compute_cross_section_groups → group_result
#   group_result → _compute_long_short → longshort_result
#   assemble → FactorBacktestResult
# ════════════════════════════════════════════════════════════════


def generate_adj_dates(
    date_index: pd.DatetimeIndex,
    adj_mode: str = "D",
) -> list:
    """Generate rebalance dates from a date index.

    Args:
        date_index: Sorted datetime index of available trading days.
        adj_mode:
            - "D"      : all trading days (daily rebalance)
            - "M-end"  : last trading day of each month
            - "W-end"  : last trading day of each week (Friday)
            - "M-begin": first trading day of each month

    Returns:
        List of pd.Timestamp (subset of date_index).
    """
    if date_index is None or len(date_index) == 0:
        return []
    if adj_mode == "D":
        return list(date_index)

    if not isinstance(date_index, pd.DatetimeIndex):
        date_index = pd.DatetimeIndex(date_index)
    df = pd.DataFrame(index=date_index)
    if adj_mode == "M-end":
        return list(df.resample("M").last().dropna().index)
    if adj_mode == "M-begin":
        return list(df.resample("MS").first().dropna().index)
    if adj_mode == "W-end":
        return list(df.resample("W-FRI").last().dropna().index)
    if adj_mode == "W-begin":
        return list(df.resample("W-MON").first().dropna().index)
    # Default: all dates
    return list(date_index)


def _compute_factor_matrix(
    close_wide: pd.DataFrame,
    factor_class: str,
    factor_params: dict[str, Any],
) -> pd.DataFrame:
    """Compute factor values for every stock in the universe.

    Iterates columns of ``close_wide`` and applies ``_compute_factor_values``
    to each stock's close series. Returns a wide DataFrame with same shape.

    Args:
        close_wide: pd.DataFrame [date × Code] of close prices.
        factor_class: Factor type (momentum, volatility, etc.).
        factor_params: Factor parameters.

    Returns:
        pd.DataFrame [date × Code] of factor values.
    """
    if close_wide is None or close_wide.empty:
        return pd.DataFrame()

    # Ensure DatetimeIndex is preserved through to the output
    date_index = close_wide.index
    is_dt = isinstance(date_index, pd.DatetimeIndex)
    cols: dict[str, pd.Series] = {}
    for code in close_wide.columns:
        s = close_wide[code].dropna()
        if len(s) < 5:
            continue
        try:
            df_one = pd.DataFrame({"date": s.index, "close": s.values})
            fv = _compute_factor_values(df_one, factor_class, factor_params)
            if fv is None or len(fv) == 0:
                continue
            # Reindex fv to use the original date index from s.index
            fv.index = s.index[: len(fv)]
            cols[code] = fv
        except Exception as exc:
            logger.warning("factor %s failed for %s: %s", factor_class, code, exc)
            continue

    if not cols:
        return pd.DataFrame()

    out = pd.DataFrame(cols)
    # Defensive: cast index to DatetimeIndex
    if is_dt and not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.DatetimeIndex(out.index)
    return out


def _compute_return_matrix(
    close_wide: pd.DataFrame,
    forward_days: int = 1,
) -> pd.DataFrame:
    """Compute forward N-day returns for every stock.

    Args:
        close_wide: pd.DataFrame [date × Code] of close prices.
        forward_days: Forward window (default 1).

    Returns:
        pd.DataFrame [date × Code] of forward returns, shifted up.
    """
    if close_wide is None or close_wide.empty:
        return pd.DataFrame()
    return close_wide.pct_change(forward_days).shift(-forward_days)


def _compute_cross_section_ic(
    factor_wide: pd.DataFrame,
    return_wide: pd.DataFrame,
    adj_dates: list,
) -> dict[str, Any]:
    """Compute cross-sectional Spearman Rank IC at each adjustment date.

    Adapted from ``~/Public/单因子回测/factor_performance.py:cal_ic()`` and
    ``QuantNodes/research/factor_test/nodes/ic_analyzer_node.py``.

    At each ``adj_date``:
        - factor_t = factor_wide.loc[t].dropna()
        - return_t = return_wide.loc[t].dropna()
        - align on stock codes
        - ic = spearmanr(factor, return) [rank IC]
        - pearson_ic = factor.corr(return) [Pearson IC for compatibility]

    Returns dict with:
        ic_mean, ic_std, icir, t_stat, win_rate (Pearson, for back-compat),
        rank_ic_mean, rank_ic_std, rank_icir, rank_ic_pos_ratio,
        ic_series: list of {date, ic, rank_ic, n_stocks}.
    """
    if factor_wide is None or factor_wide.empty or return_wide is None or return_wide.empty:
        return _empty_ic_result()

    ic_series: list[dict[str, Any]] = []
    ic_values: list[float] = []
    rank_ic_values: list[float] = []
    n_stocks_list: list[int] = []

    for d in adj_dates:
        if d not in factor_wide.index or d not in return_wide.index:
            continue
        f = factor_wide.loc[d].dropna()
        r = return_wide.loc[d].dropna()
        common = f.index.intersection(r.index)
        if len(common) < 5:
            continue
        f_al = f.loc[common]
        r_al = r.loc[common]
        try:
            pearson = float(f_al.corr(r_al))
            if pd.isna(pearson):
                continue
        except Exception:
            continue
        try:
            rank_ic = float(f_al.rank().corr(r_al.rank()))
            if pd.isna(rank_ic):
                rank_ic = pearson
        except Exception:
            rank_ic = pearson

        ic_values.append(pearson)
        rank_ic_values.append(rank_ic)
        n_stocks_list.append(len(common))
        ic_series.append({
            "date": str(d)[:10] if hasattr(d, "isoformat") else str(d),
            "ic": round(pearson, 6),
            "rank_ic": round(rank_ic, 6),
            "n_stocks": len(common),
        })

    if not ic_values:
        return _empty_ic_result()

    import numpy as np
    ic_arr = np.array(ic_values)
    rank_arr = np.array(rank_ic_values)
    n = len(ic_arr)

    ic_mean = float(ic_arr.mean())
    ic_std = float(ic_arr.std(ddof=1)) if n > 1 else 0.0
    icir = ic_mean / ic_std if ic_std > 0 else 0.0
    t_stat = ic_mean * np.sqrt(n) / ic_std if ic_std > 0 else 0.0
    win_rate = float((ic_arr > 0).sum() / n) if n > 0 else 0.0

    ric_mean = float(rank_arr.mean())
    ric_std = float(rank_arr.std(ddof=1)) if n > 1 else 0.0
    rank_icir = ric_mean / ric_std if ric_std > 0 else 0.0
    rank_pos = float((rank_arr > 0).sum() / n) if n > 0 else 0.0

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "icir": icir,
        "t_stat": t_stat,
        "win_rate": win_rate,
        "rank_ic_mean": ric_mean,
        "rank_ic_std": ric_std,
        "rank_icir": rank_icir,
        "rank_ic_pos_ratio": rank_pos,
        "ic_series": ic_series,
        "n_stocks_per_date": n_stocks_list,
    }


def _empty_ic_result() -> dict[str, Any]:
    return {
        "ic_mean": 0.0, "ic_std": 0.0, "icir": 0.0, "t_stat": 0.0, "win_rate": 0.0,
        "rank_ic_mean": 0.0, "rank_ic_std": 0.0, "rank_icir": 0.0,
        "rank_ic_pos_ratio": 0.0,
        "ic_series": [], "n_stocks_per_date": [],
    }


def _compute_cross_section_groups(
    factor_wide: pd.DataFrame,
    return_wide: pd.DataFrame,
    adj_dates: list,
    n_groups: int = 5,
    close_wide: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """Compute N-group cross-section quantile analysis.

    For each ``adj_date``:
        1. Rank stocks by factor value
        2. Assign each stock to one of N quantile groups
        3. Compute equal-weight average forward return per group
        4. Build group daily NAV curves (between consecutive adj_dates)

    Adapted from ``~/Public/单因子回测/factor_performance.py:cal_group_ret()``
    and ``QuantNodes/research/factor_test/nodes/group_analyzer_node.py``.

    Args:
        factor_wide: [date × Code] factor values.
        return_wide: [date × Code] forward returns (next period).
        adj_dates: list of rebalance dates.
        n_groups: number of quantile groups.
        close_wide: optional [date × Code] close prices for daily NAV curves.

    Returns dict with:
        quantile_returns: {G1: ann_return, ...}
        quantile_curves: {G1: [{date, value}, ...], ...}
        group_n_periods: {G1: int, ...}
    """
    if factor_wide is None or factor_wide.empty or return_wide is None or return_wide.empty:
        return {"quantile_returns": {}, "quantile_curves": {}, "group_n_periods": {}}

    valid_adj = [d for d in adj_dates if d in factor_wide.index]
    if len(valid_adj) < 2:
        return {"quantile_returns": {}, "quantile_curves": {}, "group_n_periods": {}}

    # Period returns per group: list of {group: mean_ret} at each adj date
    period_group_ret: list[dict[str, Any]] = []
    # Group membership at each adj date: {adj_date: {code: group}}
    memberships: dict[Any, dict[str, int]] = {}

    # Process all adj_dates EXCEPT the last one (no forward return for last date)
    for i in range(len(valid_adj) - 1):
        d = valid_adj[i]
        f = factor_wide.loc[d].dropna()
        r = return_wide.loc[d].dropna()
        common = f.index.intersection(r.index)
        if len(common) < n_groups:
            continue
        f_al = f.loc[common].rank(method="first")
        try:
            groups = pd.qcut(f_al, n_groups, labels=range(1, n_groups + 1), duplicates="drop")
        except Exception:
            # Fallback: equal-frequency by rank percentile
            groups = ((f_al.rank(pct=True) * n_groups).astype(int) + 1).clip(1, n_groups)
        groups = groups.astype(int)
        memberships[d] = groups.to_dict()

        # Period return: mean of fwd returns per group
        ret_per_group = {}
        for g in range(1, n_groups + 1):
            members = groups[groups == g].index
            if len(members) == 0:
                continue
            ret_per_group[f"G{g}"] = float(r.loc[members].mean())
        period_group_ret.append({"date": d, **ret_per_group})

    if not period_group_ret:
        return {"quantile_returns": {}, "quantile_curves": {}, "group_n_periods": {}}

    # Build per-group daily NAV curves
    quantile_curves: dict[str, list[dict[str, Any]]] = {f"G{g}": [] for g in range(1, n_groups + 1)}
    quantile_returns: dict[str, float] = {}
    group_n_periods: dict[str, int] = {}

    for g in range(1, n_groups + 1):
        gl = f"G{g}"
        nav = 1.0
        curve: list[dict[str, Any]] = []
        for entry in period_group_ret:
            d = entry["date"]
            ret = entry.get(gl, 0.0)
            # Append NAV at the START of this period. period_group_ret has N entries
            # (one per rebalance date, excluding the last which has no forward return),
            # so the curve gets exactly N points — one per rebalance date.
            curve.append({
                "date": str(d)[:10] if hasattr(d, "isoformat") else str(d),
                "value": round(nav, 6),
            })
            nav *= (1 + ret)
        quantile_curves[gl] = curve

        # Annual return: simple extrapolation
        n_periods = len(period_group_ret)
        if n_periods > 0:
            # Use calendar day count for accurate annualization
            from datetime import datetime
            d0 = period_group_ret[0]["date"]
            dn = period_group_ret[-1]["date"]
            if isinstance(d0, str):
                d0 = pd.Timestamp(d0)
            if isinstance(dn, str):
                dn = pd.Timestamp(dn)
            days = max((dn - d0).days, 1)
            years = days / 365.25
            ann_ret = (nav ** (1 / years) - 1) if years > 0 and nav > 0 else 0.0
            quantile_returns[gl] = float(ann_ret)
            group_n_periods[gl] = n_periods

    # Per-group metrics: sharpe / max_drawdown / win_rate / turnover / n_stocks
    from .metrics import evaluation
    group_metrics: dict[str, dict[str, float]] = {}
    for g in range(1, n_groups + 1):
        gl = f"G{g}"
        curve = quantile_curves.get(gl, [])
        sharpe = 0.0
        max_dd = 0.0
        win_rate = 0.0
        if len(curve) >= 2:
            net = pd.Series(
                [pt["value"] for pt in curve],
                index=[pd.Timestamp(pt["date"]) for pt in curve],
            )
            ev = evaluation(net, list(net.index), trading_days=252)
            sharpe = float(ev.get("sharpe", 0.0))
            max_dd = float(ev.get("max_drawdown", 0.0))
            win_rate = float(ev.get("win_rate", 0.0))
        n_stocks = 0
        if memberships and valid_adj:
            first_d = valid_adj[0]
            if first_d in memberships:
                n_stocks = sum(1 for c, gg in memberships[first_d].items() if gg == g)
        turnover = _compute_single_group_turnover(memberships, valid_adj, g)
        group_metrics[gl] = {
            "sharpe": round(sharpe, 6),
            "max_drawdown": round(max_dd, 6),
            "win_rate": round(win_rate, 6),
            "turnover": round(turnover, 6),
            "n_stocks": n_stocks,
        }

    return {
        "quantile_returns": quantile_returns,
        "quantile_curves": quantile_curves,
        "group_n_periods": group_n_periods,
        "group_metrics": group_metrics,
    }


def _compute_long_short(
    group_curves: dict[str, list[dict[str, Any]]],
    adj_dates: list,
    factor_direction: int = 1,
    trading_days: int = 252,
) -> dict[str, Any]:
    """Build long-short pair from group quantile curves.

    Args:
        group_curves: {G1: [{date, value}], ...} from _compute_cross_section_groups.
        adj_dates: list of rebalance dates (aligned with curve dates).
        factor_direction: 1 = larger factor → higher group is long (G_n long);
            -1 = smaller factor → lower group is long (G_1 long).
        trading_days: annualization factor.

    Returns dict with:
        longshort_ann_return, longshort_sharpe, longshort_mdd,
        longshort_curve: [{date, value}, ...].
    """
    if not group_curves:
        return {
            "longshort_ann_return": 0.0, "longshort_sharpe": 0.0,
            "longshort_mdd": 0.0, "longshort_curve": [],
        }

    n_groups = len(group_curves)
    long_g = f"G{n_groups}" if factor_direction == 1 else "G1"
    short_g = "G1" if factor_direction == 1 else f"G{n_groups}"

    long_curve = group_curves.get(long_g, [])
    short_curve = group_curves.get(short_g, [])

    if not long_curve or not short_curve:
        return {
            "longshort_ann_return": 0.0, "longshort_sharpe": 0.0,
            "longshort_mdd": 0.0, "longshort_curve": [],
        }

    # Build aligned NAV series
    long_s = pd.Series(
        [pt["value"] for pt in long_curve],
        index=[pd.Timestamp(pt["date"]) for pt in long_curve],
    )
    short_s = pd.Series(
        [pt["value"] for pt in short_curve],
        index=[pd.Timestamp(pt["date"]) for pt in short_curve],
    )
    common = long_s.index.intersection(short_s.index)
    if len(common) < 2:
        return {
            "longshort_ann_return": 0.0, "longshort_sharpe": 0.0,
            "longshort_mdd": 0.0, "longshort_curve": [],
        }
    long_s = long_s.loc[common]
    short_s = short_s.loc[common]

    # Long-short simple interest: long - short + 1
    ls_simp = long_s - short_s + 1
    # Reindexed to include daily frequency from close prices isn't strictly
    # required here; we use period-level returns for evaluation.

    # Compute metrics via metrics.evaluation
    from .metrics import evaluation

    # adj_dates aligned to ls_simp.index
    valid_adj = [d for d in adj_dates if d in ls_simp.index]
    metrics = evaluation(ls_simp, valid_adj, trading_days=trading_days)

    ls_curve = [{"date": str(d)[:10], "value": round(float(v), 6)} for d, v in ls_simp.items()]

    return {
        "longshort_ann_return": metrics["annual_return"],
        "longshort_sharpe": metrics["sharpe"],
        "longshort_mdd": metrics["max_drawdown"],
        "longshort_curve": ls_curve,
    }


class _DummyLoader:
    """Minimal QN loader stub — all data provided via context already."""
    @staticmethod
    def load_h5(*args, **kwargs):
        return None


def run_factor_backtest_universe(
    close_wide: pd.DataFrame,
    factor_class: str,
    factor_params: dict[str, Any],
    index_close: Optional[pd.Series] = None,
    adj_mode: str = "D",
    n_groups: int = 5,
    factor_direction: int = 1,
    forward_days: int = 1,
    universe: str = "",
    tradable: dict[str, pd.DataFrame] | None = None,
) -> FactorBacktestResult:
    """Cross-section (universe) factor backtest.

    Uses QuantNodes ICAnalyzerNode / GroupAnalyzerNode / LongShortNode for
    analysis. Data format conversion handled by quantnodes_adapter.

    Args:
        close_wide: pd.DataFrame [date × Code] of close prices.
        factor_class: Factor type (momentum, volatility, ma_cross, etc.).
        factor_params: Factor construction parameters.
        index_close: Optional pd.Series of benchmark close prices (for hedging).
        adj_mode: "D" (daily) or "M-end" (month-end rebalance) or "W-end".
        n_groups: Number of quantile groups (default 5).
        factor_direction: 1 = higher factor → long, -1 = reverse.
        forward_days: Forward return period (default 1).
        universe: Universe label for the result metadata.

    Returns:
        FactorBacktestResult with all multi-stock metrics populated.
    """
    if close_wide is None or close_wide.empty:
        logger.warning("empty close_wide for universe backtest")
        return FactorBacktestResult(universe=universe, adj_mode=adj_mode)

    # 1. Factor matrix (DatetimeIndex, str codes)
    factor_wide = _compute_factor_matrix(close_wide, factor_class, factor_params)
    if factor_wide.empty:
        logger.warning("factor matrix empty for class=%s", factor_class)
        return FactorBacktestResult(universe=universe, adj_mode=adj_mode)

    # 2. Convert to QuantNodes format (int64 yyyymmdd, int codes)
    from .quantnodes_adapter import (
        build_code_map,
        build_qn_context,
        convert_wide_to_qn,
        extract_group_result,
        extract_ic_result,
        extract_longshort_result,
    )

    factor_valid = factor_wide.dropna(how="all").dropna(axis=1, how="all")
    code_map = build_code_map(factor_valid.columns)
    common_dates = close_wide.index.intersection(factor_valid.index)
    price_aligned = close_wide.loc[common_dates, factor_valid.columns]
    price_qn = convert_wide_to_qn(price_aligned, code_map)
    factor_qn = convert_wide_to_qn(factor_valid.loc[common_dates], code_map)

    # 2b. TradabilityFilter + FactorPreprocess (full QN pipeline)
    # Only runs when real tradable data is provided. The processed factor
    # has NaN for non-tradable stocks, so we use our own IC/Group/LongShort
    # implementations (which handle sparse factors via index intersection)
    # instead of QuantNodes' nodes (which fail on sparse factors).
    use_qn_analysis = True
    if tradable is not None:
        adj_dates = list(factor_valid.loc[common_dates].index)
        ctx = build_qn_context(
            factor_wide=factor_valid.loc[common_dates],
            close_wide=price_aligned,
            adj_dates=adj_dates,
            index_close=index_close,
            tradable=tradable,
        )
        ctx["LoadData"]["_loader"] = _DummyLoader()

        # TradabilityFilterNode: marks non-tradable as NaN
        from QuantNodes.research.factor_test.nodes.tradability_filter_node import (
            TradabilityFilterNode,
        )

        tf_node = TradabilityFilterNode(config={
            "tradable": {"no_st": True, "no_suspended": True, "no_up_down_limit": True, "min_ipo_days": 60},
        })
        tradable_mask = tf_node.execute(context=ctx)
        ctx["TradabilityFilter"] = tradable_mask

        # FactorPreprocessNode: fill NaN, winsorize, standardize
        from QuantNodes.research.factor_test.nodes.factor_preprocess_node import (
            FactorPreprocessNode,
        )

        fp_node = FactorPreprocessNode(config={
            "missing": "ind_avg",
            "extreme": "pct_shrink",
            "norm": "zscore",
        })
        processed_qn = fp_node.execute(context=ctx)
        # Convert back to DatetimeIndex+str-codes for our own IC/Group/LongShort
        from .quantnodes_adapter import _qn_date_to_str
        proc_str_idx = [_qn_date_to_str(d) for d in processed_qn.index]
        proc_date_idx = pd.DatetimeIndex(proc_str_idx)
        # Map int code columns back to str codes
        inv_code_map = {v: k for k, v in code_map.items()}
        str_cols = [inv_code_map.get(c, str(c)) for c in processed_qn.columns]
        processed_wide = pd.DataFrame(
            processed_qn.values, index=proc_date_idx, columns=str_cols,
        )
        # Compute return matrix from price_aligned (DatetimeIndex)
        # Match processed_wide dates only
        return_wide = _compute_return_matrix(price_aligned, forward_days)
        common_proc_dates = processed_wide.index.intersection(return_wide.index)
        proc_factor_w = processed_wide.loc[common_proc_dates]
        proc_return_w = return_wide.loc[common_proc_dates]

        # Use our own IC/Group/LongShort (handles NaN from tradability filter)
        adj_qn = generate_adj_dates(common_proc_dates, adj_mode)
        ic_res_full = _compute_cross_section_ic(proc_factor_w, proc_return_w, adj_qn)
        group_res_full = _compute_cross_section_groups(
            proc_factor_w, proc_return_w, adj_qn, n_groups, price_aligned,
        )
        ls_res_full = _compute_long_short(
            group_res_full.get("quantile_curves", {}), adj_qn, factor_direction,
        )

        # Assemble result
        quantile_returns = group_res_full.get("quantile_returns", {})
        n_groups_actual = n_groups
        if quantile_returns:
            long_g = f"G{n_groups}" if factor_direction == 1 else "G1"
            top_ann = quantile_returns.get(long_g, 0.0)
        else:
            top_ann = 0.0

        # Compute turnover from our group analysis
        turnover = _compute_group_turnover(price_aligned, factor_wide, adj_dates, n_groups, factor_direction) if factor_wide is not None else 0.0

        # Build ic_series for extract_group_result
        ic_series = ic_res_full.get("ic_series", [])

        # Convert n_stocks_per_date to list of dicts
        n_stocks_raw = ic_res_full.get("n_stocks_per_date", [])
        ic_series_full = ic_res_full.get("ic_series", [])
        n_stocks_per_date = []
        for i, n in enumerate(n_stocks_raw):
            date_str = ic_series_full[i]["date"] if i < len(ic_series_full) else ""
            n_stocks_per_date.append({"date": date_str, "n": n})

        return FactorBacktestResult(
            ic_mean=ic_res_full["ic_mean"],
            ic_std=ic_res_full["ic_std"],
            icir=ic_res_full["icir"],
            t_stat=ic_res_full["t_stat"],
            win_rate=ic_res_full["win_rate"],
            annual_return=top_ann,
            max_drawdown=0.0,
            turnover=turnover,
            quantile_returns=quantile_returns,
            ic_series=ic_series,
            quantile_curves=group_res_full.get("quantile_curves", {}),
            rank_ic_mean=ic_res_full["rank_ic_mean"],
            rank_ic_std=ic_res_full["rank_ic_std"],
            rank_icir=ic_res_full["rank_icir"],
            rank_ic_pos_ratio=ic_res_full["rank_ic_pos_ratio"],
            longshort_ann_return=ls_res_full["longshort_ann_return"],
            longshort_sharpe=ls_res_full["longshort_sharpe"],
            longshort_mdd=ls_res_full["longshort_mdd"],
            longshort_curve=ls_res_full["longshort_curve"],
            universe=universe,
            adj_mode=adj_mode,
            n_stocks_per_date=n_stocks_per_date,
            group_metrics=group_res_full.get("group_metrics", {}),
            total_rebalances=len(adj_dates),
            valid_rebalances=len(ic_series),
        )

    # 3. IC / Group / LongShort — use our own implementations (handle NaN correctly)
    return_wide = _compute_return_matrix(price_aligned, forward_days)
    adj_dates = generate_adj_dates(close_wide.index, adj_mode)
    # Filter adj_dates to only those present in all relevant DataFrames
    adj_dates = [d for d in adj_dates if d in return_wide.index and d in factor_wide.index]

    ic_res = _compute_cross_section_ic(factor_wide, return_wide, adj_dates)
    ic_series = ic_res.get("ic_series", [])

    group_res = _compute_cross_section_groups(
        factor_wide, return_wide, adj_dates, n_groups, price_aligned,
    )
    ls_res = _compute_long_short(
        group_res.get("quantile_curves", {}), adj_dates, factor_direction,
    )

    # Top group annual return
    quantile_returns = group_res.get("quantile_returns", {})
    n_groups_actual = n_groups
    if quantile_returns:
        long_g = f"G{n_groups}" if factor_direction == 1 else "G1"
        top_ann = quantile_returns.get(long_g, 0.0)
    else:
        top_ann = 0.0

    # Convert n_stocks_per_date to list of dicts
    n_stocks_raw = ic_res.get("n_stocks_per_date", [])
    ic_series_data = ic_res.get("ic_series", [])
    n_stocks_per_date = []
    for i, n in enumerate(n_stocks_raw):
        date_str = ic_series_data[i]["date"] if i < len(ic_series_data) else ""
        n_stocks_per_date.append({"date": date_str, "n": n})

    return FactorBacktestResult(
        ic_mean=ic_res["ic_mean"],
        ic_std=ic_res["ic_std"],
        icir=ic_res["icir"],
        t_stat=ic_res["t_stat"],
        win_rate=ic_res["win_rate"],
        annual_return=top_ann,
        max_drawdown=0.0,
        turnover=_compute_group_turnover(price_aligned, factor_wide, adj_dates, n_groups, factor_direction),
        quantile_returns=quantile_returns,
        ic_series=ic_series,
        quantile_curves=group_res.get("quantile_curves", {}),
        rank_ic_mean=ic_res["rank_ic_mean"],
        rank_ic_std=ic_res["rank_ic_std"],
        rank_icir=ic_res["rank_icir"],
        rank_ic_pos_ratio=ic_res.get("rank_ic_pos_ratio", 0.0),
        longshort_ann_return=ls_res["longshort_ann_return"],
        longshort_sharpe=ls_res["longshort_sharpe"],
        longshort_mdd=ls_res["longshort_mdd"],
        longshort_curve=ls_res["longshort_curve"],
        universe=universe,
        adj_mode=adj_mode,
        n_stocks_per_date=n_stocks_per_date,
        group_metrics=group_res.get("group_metrics", {}),
        total_rebalances=len(adj_dates),
        valid_rebalances=len(ic_series),
    )


def _compute_group_turnover(
    close_wide: pd.DataFrame,
    factor_wide: pd.DataFrame,
    adj_dates: list,
    n_groups: int = 5,
    factor_direction: int = 1,
) -> float:
    """Average turnover of the long (top) group across rebalance periods.

    Turnover = average fraction of stocks in the long group at time t
    that are NOT in the long group at time t-1.
    """
    valid_adj = [d for d in adj_dates if d in factor_wide.index]
    if len(valid_adj) < 2:
        return 0.0

    long_label = f"G{n_groups}" if factor_direction == 1 else "G1"
    prev_long: Optional[set] = None
    turnovers: list[float] = []

    for d in valid_adj:
        f = factor_wide.loc[d].dropna()
        if len(f) < n_groups:
            continue
        try:
            groups = pd.qcut(f.rank(method="first"), n_groups, labels=range(1, n_groups + 1), duplicates="drop").astype(int)
        except Exception:
            continue
        cur_long = set(groups[groups == (n_groups if factor_direction == 1 else 1)].index)
        if prev_long is not None and cur_long:
            changed = len(cur_long.symmetric_difference(prev_long))
            total = len(cur_long | prev_long)
            if total > 0:
                turnovers.append(changed / total)
        prev_long = cur_long

    return float(np.mean(turnovers)) if turnovers else 0.0


def _compute_single_group_turnover(
    memberships: dict[Any, dict[str, int]],
    valid_adj: list,
    group_num: int,
) -> float:
    """Turnover for one specific group, using pre-computed memberships.

    Avoids re-running qcut; uses the memberships dict produced by
    ``_compute_cross_section_groups``.
    """
    if len(valid_adj) < 2:
        return 0.0
    prev_members: Optional[set] = None
    turnovers: list[float] = []
    for d in valid_adj:
        if d not in memberships:
            continue
        cur_members = {c for c, g in memberships[d].items() if g == group_num}
        if prev_members is not None and cur_members:
            changed = len(cur_members.symmetric_difference(prev_members))
            total = len(cur_members | prev_members)
            if total > 0:
                turnovers.append(changed / total)
        prev_members = cur_members
    return float(np.mean(turnovers)) if turnovers else 0.0