"""Extract backtest metrics from PipelineRunner context."""
from __future__ import annotations

from typing import Any


def safe_float(x: Any, default: float | None = None) -> float | None:
    """Safely cast to float, handling NaN/None/non-numeric."""
    if x is None:
        return default
    try:
        v = float(x)
        if v != v:  # NaN check
            return default
        return v
    except (TypeError, ValueError):
        return default


def extract_full_backtest_from_ctx(ctx: dict) -> dict:
    """Extract full backtest data from PipelineRunner ctx.

    Returns dict with:
      - ic_mean, rank_ic_mean, icir, rank_icir, win_rate, ic_std
      - ic_series: [{date, ic}, ...]
      - group_metrics: {G1: {annual_return, sharpe, ...}, ...}
      - longshort_ann_return, longshort_sharpe, longshort_max_dd

    Defensive: missing fields -> None (not crash).
    """
    out: dict = {
        "ic_mean": None,
        "rank_ic_mean": None,
        "icir": None,
        "rank_icir": None,
        "win_rate": None,
        "ic_std": None,
        "ic_series": [],
        "group_metrics": {},
        "longshort_ann_return": None,
        "longshort_sharpe": None,
        "longshort_max_dd": None,
    }

    # ICAnalyzer
    ic_node = ctx.get("ICAnalyzer") or {}
    ic_result = ic_node.get("ic_result") if isinstance(ic_node, dict) else None
    if ic_result is not None and hasattr(ic_result, "get"):
        out["ic_mean"] = safe_float(ic_result.get("IC均值"))
        out["ic_std"] = safe_float(ic_result.get("IC标准差"))
        out["icir"] = safe_float(ic_result.get("ICIR"))
        out["win_rate"] = safe_float(ic_result.get("IC为正比例"))

    rank_ic_result = ic_node.get("rank_ic_result") if isinstance(ic_node, dict) else None
    if rank_ic_result is not None and hasattr(rank_ic_result, "get"):
        out["rank_ic_mean"] = safe_float(rank_ic_result.get("Rank IC均值"))
        out["rank_icir"] = safe_float(rank_ic_result.get("Rank ICIR"))

    ic_series_obj = ic_node.get("ic") if isinstance(ic_node, dict) else None
    if ic_series_obj is not None and hasattr(ic_series_obj, "items"):
        out["ic_series"] = [
            {"date": int(d), "ic": safe_float(v, 0.0)}
            for d, v in ic_series_obj.items()
            if safe_float(v) is not None
        ]

    # GroupAnalyzer
    ga = ctx.get("GroupAnalyzer") or {}
    if isinstance(ga, dict):
        group_eva_abs = ga.get("group_eva_abs")
        turnover_obj = ga.get("turnover")
        n_groups = ga.get("n_groups", 5)

        if group_eva_abs is not None and hasattr(group_eva_abs, "loc"):
            gm: dict = {}
            for g in range(1, n_groups + 1):
                if g not in group_eva_abs.columns:
                    continue
                gm[f"G{g}"] = {
                    "annual_return": safe_float(group_eva_abs.loc["AnnualRt", g], 0.0),
                    "sharpe": safe_float(group_eva_abs.loc["SR", g], 0.0),
                    "max_drawdown": safe_float(group_eva_abs.loc["MDD", g], 0.0),
                    "win_rate": safe_float(group_eva_abs.loc["WinRatio", g], 0.0),
                    "turnover": (
                        safe_float(turnover_obj.loc[g], 0.0)
                        if (
                            turnover_obj is not None
                            and hasattr(turnover_obj, "loc")
                            and g in turnover_obj.index
                        )
                        else 0.0
                    ),
                    "n_stocks": 0,
                }
            out["group_metrics"] = gm

        # Extract group NAV time series from GroupAnalyzer ctx
        daily_net = ga.get("daily_net_simp")
        if daily_net is not None and hasattr(daily_net, "columns"):
            nav_series: dict = {}
            for g in daily_net.columns:
                col = daily_net[g].dropna()
                nav_series[f"G{g}"] = [
                    {"date": int(d.timestamp() * 1000) if hasattr(d, "timestamp") else int(d), "nav": float(v)}
                    for d, v in col.items()
                ]
            out["equity_curve"] = nav_series
            out["group_nav_series"] = nav_series

    # LongShort
    ls = ctx.get("LongShort") or {}
    if isinstance(ls, dict):
        net = ls.get("net")
        if net is not None and hasattr(net, "iloc"):
            try:
                ls_curve = net.iloc[:, 0] if hasattr(net, "iloc") else None
                if ls_curve is not None and len(ls_curve) > 1:
                    n_periods = len(ls_curve)
                    periods_per_year = 12
                    total_ret = float(ls_curve.iloc[-1] / ls_curve.iloc[0] - 1)
                    out["longshort_ann_return"] = (
                        (1 + total_ret) ** (periods_per_year / n_periods) - 1
                        if n_periods > 0
                        else 0.0
                    )
                    peak = ls_curve.cummax()
                    dd = (ls_curve - peak) / peak
                    out["longshort_max_dd"] = float(dd.min())
                    if hasattr(ls, "period_ret") and ls["period_ret"] is not None:
                        pr = ls["period_ret"]
                        if hasattr(pr, "std"):
                            std = float(pr.std(ddof=1))
                            mean = float(pr.mean())
                            out["longshort_sharpe"] = (
                                (mean / std * (periods_per_year**0.5)) if std > 0 else 0.0
                            )
            except Exception:
                pass

    return out
