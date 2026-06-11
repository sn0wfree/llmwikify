"""Adapter between llmwikify DataFrames and QuantNodes factor_test format.

QuantNodes factor_test nodes expect:
  - int64 yyyymmdd index (e.g. 20240131)
  - int64 stock code columns (e.g. 1, 2, 3, ...)
  - Single-column DataFrames for stklist / trade_dt

This module provides:
  - date/datetime → int64 yyyymmdd conversion
  - string code "000001.SZ" → int64 mapping
  - Context dict building for QuantNodes nodes
  - Result extraction from QuantNodes context
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Date helpers ───────────────────────────────────────────


def _qn_date_to_str(d) -> str:
    """Convert QuantNodes int yyyymmdd (e.g. 20240101) to ISO string."""
    s = str(int(d))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _parse_qn_date(s: str):
    """Parse a date string (ISO or int-like) to datetime."""
    from datetime import datetime
    s = s.replace("-", "")
    return datetime.strptime(s[:8], "%Y%m%d")


# ─── Format conversion ──────────────────────────────────────


def dates_to_int(index: pd.DatetimeIndex | pd.Index) -> np.ndarray:
    """Convert DatetimeIndex or datetime-like index to int64 yyyymmdd."""
    if isinstance(index, pd.DatetimeIndex):
        return np.array([int(d.strftime("%Y%m%d")) for d in index], dtype=np.int64)
    # Fallback: try parsing as strings
    return np.array([int(str(d)[:8]) for d in index], dtype=np.int64)


def build_code_map(columns: pd.Index) -> dict[str, int]:
    """Map string stock codes to sequential int64.

    Returns dict: {"000001.SZ": 1, "600519.SH": 2, ...}
    """
    return {str(c): i + 1 for i, c in enumerate(columns)}


def convert_wide_to_qn(
    wide_df: pd.DataFrame,
    code_map: dict[str, int],
) -> pd.DataFrame:
    """Convert a wide DataFrame [date × code] to QuantNodes format.

    Input: DatetimeIndex, string columns
    Output: int64 yyyymmdd index, int64 columns (numpy.int64 for index matching)
    """
    if wide_df is None or wide_df.empty:
        return pd.DataFrame()

    out = wide_df.copy()
    out.index = np.array(dates_to_int(out.index), dtype=np.int64)
    out.columns = np.array([code_map.get(str(c), 0) for c in out.columns], dtype=np.int64)
    return out


# ─── Context building ───────────────────────────────────────


def build_qn_context(
    factor_wide: pd.DataFrame,
    close_wide: pd.DataFrame,
    adj_dates: list | None = None,
    index_close: pd.Series | None = None,
    id_citic1: pd.DataFrame | None = None,
    mv_float: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a minimal context dict for QuantNodes analysis nodes.

    This creates the context keys needed by ICAnalyzerNode, GroupAnalyzerNode,
    and LongShortNode WITHOUT going through LoadDataNode/SamplePoolFilter/etc.

    Args:
        factor_wide: [date × Code] factor values (DatetimeIndex, str codes)
        close_wide: [date × Code] close prices (DatetimeIndex, str codes)
        adj_dates: list of pd.Timestamp rebalance dates (optional, for preprocess)
        index_close: pd.Series of benchmark close prices (optional)
        id_citic1: [date × Code] industry codes (optional, for preprocess)
        mv_float: [date × Code] market cap (optional, for preprocess)

    Returns:
        dict with keys matching QuantNodes context format (int64 index/columns)
    """
    code_map = build_code_map(close_wide.columns)

    price = convert_wide_to_qn(close_wide, code_map)
    factor = convert_wide_to_qn(factor_wide, code_map)

    ctx: dict[str, Any] = {}

    # LoadData-style dict (for nodes that read from context)
    load_data: dict[str, Any] = {
        "factor": factor,
        "price": price,
    }

    # stklist / trade_dt (single-column DataFrames)
    stklist = pd.DataFrame({"stklist": list(code_map.values())})
    dates_int = dates_to_int(factor.index)
    trade_dt = pd.DataFrame({"trade_dt": dates_int})
    load_data["stklist"] = stklist
    load_data["trade_dt"] = trade_dt

    # Index close prices (for hedge benchmarks)
    if index_close is not None and not index_close.empty:
        idx_int = dates_to_int(index_close.index)
        index_cp = pd.DataFrame(
            {0: index_close.values}, index=idx_int
        )
        load_data["index_cp"] = index_cp
    else:
        load_data["index_cp"] = pd.DataFrame()

    # Optional data (for preprocessing)
    if id_citic1 is not None and not id_citic1.empty:
        load_data["id_citic1"] = convert_wide_to_qn(id_citic1, code_map)
    else:
        load_data["id_citic1"] = None

    if mv_float is not None and not mv_float.empty:
        load_data["mv_float"] = convert_wide_to_qn(mv_float, code_map)
    else:
        load_data["mv_float"] = None

    # Tradability defaults (all tradable)
    n_dates, n_stocks = factor.shape
    ones = pd.DataFrame(1.0, index=factor.index, columns=factor.columns)
    load_data["st"] = pd.DataFrame(0, index=factor.index, columns=factor.columns)
    load_data["suspend"] = pd.DataFrame(0, index=factor.index, columns=factor.columns)
    load_data["ud_limit"] = pd.DataFrame(0, index=factor.index, columns=factor.columns)
    load_data["ipo_days"] = pd.DataFrame(360, index=factor.index, columns=factor.columns)

    ctx["LoadData"] = load_data

    # AdjustDate (if provided)
    if adj_dates is not None and adj_dates:
        adj_int = dates_to_int(pd.DatetimeIndex(adj_dates))
        ctx["AdjustDate"] = pd.DataFrame({"adj_date": adj_int})

    # Ensure all int64 DataFrames use numpy.int64 for consistent index matching
    for key in ["factor", "price"]:
        if key in load_data and load_data[key] is not None:
            df = load_data[key]
            if not df.empty:
                df.index = df.index.astype(np.int64)
                df.columns = df.columns.astype(np.int64)

    return ctx


# ─── Result extraction ──────────────────────────────────────


def extract_ic_result(
    ic_result: pd.Series,
    rank_ic_result: pd.Series,
) -> dict[str, float]:
    """Extract IC metrics from QuantNodes ICAnalyzer output."""
    return {
        "ic_mean": float(ic_result.get("IC均值", 0.0)),
        "ic_std": float(ic_result.get("IC标准差", 0.0)),
        "icir": float(ic_result.get("ICIR", 0.0)),
        "t_stat": float(ic_result.get("IC_T值", 0.0)),
        "win_rate": float(ic_result.get("IC为正比例", 0.0)),
        "rank_ic_mean": float(rank_ic_result.get("rankIC均值", 0.0)),
        "rank_ic_std": float(rank_ic_result.get("rankIC标准差", 0.0)),
        "rank_icir": float(rank_ic_result.get("rankICIR", 0.0)),
        "rank_ic_pos_ratio": float(rank_ic_result.get("rankIC为正比例", 0.0)),
    }


def extract_group_result(
    group_result: dict[str, Any],
    ic_series: list[dict] | None = None,
) -> dict[str, Any]:
    """Extract quantile results from QuantNodes GroupAnalyzer output."""
    ga = group_result
    n_groups = ga.get("n_groups", 5)

    # Quantile returns (annualized from group_eva_abs)
    quantile_returns: dict[str, float] = {}
    quantile_curves: dict[str, list[dict]] = {}

    # daily_net_simp: DataFrame [dates × groups] (columns are 1..N)
    daily_net = ga.get("daily_net_simp")
    if daily_net is not None and not daily_net.empty:
        for g in range(1, n_groups + 1):
            if g in daily_net.columns:
                curve = [
                    {"date": _qn_date_to_str(d), "value": round(float(v), 6)}
                    for d, v in daily_net[g].items()
                ]
                quantile_curves[f"G{g}"] = curve
                # Annual return from last value
                if len(curve) >= 2:
                    start_val = curve[0]["value"]
                    end_val = curve[-1]["value"]
                    if start_val > 0 and end_val > 0:
                        try:
                            d0 = datetime.fromisoformat(curve[0]["date"])
                            d1 = datetime.fromisoformat(curve[-1]["date"])
                            years = max((d1 - d0).days / 365.25, 0.01)
                            ann_ret = (end_val / start_val) ** (1 / years) - 1
                            quantile_returns[f"G{g}"] = float(ann_ret)
                        except (ValueError, TypeError):
                            pass

    # Group evaluation (from group_eva_exc)
    group_eva = ga.get("group_eva_exc")
    group_eva_abs = ga.get("group_eva_abs")

    # Turnover
    turnover_df = ga.get("turnover")
    avg_turnover = 0.0
    if turnover_df is not None and hasattr(turnover_df, "mean"):
        try:
            avg_turnover = float(turnover_df.mean().mean())
        except Exception:
            pass

    return {
        "quantile_returns": quantile_returns,
        "quantile_curves": quantile_curves,
        "turnover": avg_turnover,
        "n_groups": n_groups,
        "group_eva": group_eva,
        "group_eva_abs": group_eva_abs,
    }


def extract_longshort_result(
    ls_result: dict[str, Any],
) -> dict[str, Any]:
    """Extract long-short metrics from QuantNodes LongShort output."""
    eva = ls_result.get("eva_total")
    net = ls_result.get("net")

    # Extract from eva_total DataFrame (rows=metrics, cols=['多头超额','空头超额','多空'])
    sharpe = 0.0
    ann_return = 0.0
    mdd = 0.0
    win_rate = 0.0

    if eva is not None and not eva.empty:
        try:
            if "SR" in eva.index and "多空" in eva.columns:
                sharpe = float(eva.loc["SR", "多空"])
            if "AnnualRt" in eva.index and "多空" in eva.columns:
                ann_return = float(eva.loc["AnnualRt", "多空"])
            if "MDD" in eva.index and "多空" in eva.columns:
                mdd = float(eva.loc["MDD", "多空"])
            if "WinRatio" in eva.index and "多空" in eva.columns:
                win_rate = float(eva.loc["WinRatio", "多空"])
        except Exception:
            pass

    # Long-short curve from net DataFrame
    longshort_curve: list[dict] = []
    if net is not None and not net.empty and "多空" in net.columns:
        ls_series = net["多空"]
        longshort_curve = [
            {"date": str(d)[:10], "value": round(float(v), 6)}
            for d, v in ls_series.items()
        ]

    return {
        "longshort_ann_return": ann_return,
        "longshort_sharpe": sharpe,
        "longshort_mdd": mdd,
        "longshort_win_rate": win_rate,
        "longshort_curve": longshort_curve,
    }


__all__ = [
    "dates_to_int",
    "build_code_map",
    "convert_wide_to_qn",
    "build_qn_context",
    "extract_ic_result",
    "extract_group_result",
    "extract_longshort_result",
]
