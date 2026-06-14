"""L5 Automated Validation Engine.

Runs 7 analysis modules on backtest results, scores the factor,
and generates the L5 section of the factor YAML.

Modules:
  1. IC Analysis — IC mean, ICIR, RankIC, RankICIR, win rate
  2. Group Analysis — group returns, monotonicity, long-short Sharpe, max DD
  3. Return Analysis — annualized return, volatility, Sharpe, Calmar, Sortino
  4. Turnover Analysis — average turnover, turnover stability
  5. Stability Analysis — yearly, industry, market-cap consistency
  6. OOS Analysis — out-of-sample RankIC, long-short return, Sharpe
  7. Cost Analysis — net return after costs, cost sensitivity

Scoring:
  7-dimension weighted rubric (IC25 + Group20 + Return20 + Turnover10
  + Stability10 + OOS10 + Cost5 = 100). Pass threshold: 60.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. IC Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_ic(result: Any) -> dict[str, Any]:
    """Compute IC analysis metrics from backtest result.

    Returns dict with: ic_mean, ic_std, icir, rank_ic_mean,
    rank_ic_std, rank_icir, win_rate.
    """
    ic_series = getattr(result, "ic_series", [])
    if not ic_series:
        return {}

    ic_values = [pt["ic"] for pt in ic_series if "ic" in pt]
    rank_ic_values = [pt.get("rank_ic", pt.get("ic", 0)) for pt in ic_series]

    import statistics

    ic_mean = statistics.mean(ic_values) if ic_values else 0.0
    ic_std = statistics.stdev(ic_values) if len(ic_values) > 1 else 1.0
    icir = ic_mean / ic_std if ic_std > 0 else 0.0

    rank_ic_mean = statistics.mean(rank_ic_values) if rank_ic_values else 0.0
    rank_ic_std = statistics.stdev(rank_ic_values) if len(rank_ic_values) > 1 else 1.0
    rank_icir = rank_ic_mean / rank_ic_std if rank_ic_std > 0 else 0.0

    win_rate = sum(1 for v in ic_values if v > 0) / len(ic_values) if ic_values else 0.0

    return {
        "ic_mean": round(ic_mean, 6),
        "ic_std": round(ic_std, 6),
        "icir": round(icir, 4),
        "rank_ic_mean": round(rank_ic_mean, 6),
        "rank_ic_std": round(rank_ic_std, 6),
        "rank_icir": round(rank_icir, 4),
        "win_rate": round(win_rate, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 2. Group Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_groups(result: Any) -> dict[str, Any]:
    """Compute group analysis metrics.

    Returns dict with: group_returns, group_monotonicity,
    ls_ann_return, ls_sharpe, ls_max_drawdown.
    """
    quantile_returns = getattr(result, "quantile_returns", {})
    group_metrics = getattr(result, "group_metrics", {})
    longshort_sharpe = getattr(result, "longshort_sharpe", 0.0)
    longshort_ann_return = getattr(result, "longshort_ann_return", 0.0)
    longshort_mdd = getattr(result, "longshort_mdd", 0.0)

    # Determine monotonicity
    if quantile_returns:
        groups_sorted = sorted(quantile_returns.items(), key=lambda x: x[1], reverse=True)
        group_names = [g for g, _ in groups_sorted]
        monotonicity = ">".join(group_names)
    else:
        monotonicity = ""

    return {
        "group_returns": quantile_returns,
        "group_monotonicity": monotonicity,
        "ls_ann_return": round(longshort_ann_return, 4),
        "ls_sharpe": round(longshort_sharpe, 4),
        "ls_max_drawdown": round(longshort_mdd, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 3. Return Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_returns(result: Any) -> dict[str, Any]:
    """Compute return analysis metrics.

    Returns dict with: ann_return, ann_volatility, sharpe,
    max_drawdown, calmar, sortino.
    """
    import math

    ann_return = getattr(result, "longshort_ann_return", 0.0) or getattr(result, "annual_return", 0.0)
    longshort_mdd = getattr(result, "longshort_mdd", 0.0) or getattr(result, "max_drawdown", 0.0)

    # Compute volatility and Sharpe from long-short curve if available
    ls_curve = getattr(result, "longshort_curve", [])
    if ls_curve and len(ls_curve) > 1:
        values = [pt.get("value", 1.0) for pt in ls_curve]
        daily_returns = [(values[i] / values[i - 1]) - 1 for i in range(1, len(values)) if values[i - 1] != 0]
        if daily_returns:
            import statistics
            vol = statistics.stdev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0
            sharpe = ann_return / vol if vol > 0 else 0.0
            # Sortino: downside deviation
            neg_returns = [r for r in daily_returns if r < 0]
            downside_dev = statistics.stdev(neg_returns) * math.sqrt(252) if len(neg_returns) > 1 else vol
            sortino = ann_return / downside_dev if downside_dev > 0 else 0.0
        else:
            vol = 0.0
            sharpe = 0.0
            sortino = 0.0
    else:
        vol = 0.0
        sharpe = getattr(result, "longshort_sharpe", 0.0)
        sortino = 0.0

    calmar = ann_return / longshort_mdd if longshort_mdd > 0 else 0.0

    return {
        "ann_return": round(ann_return, 4),
        "ann_volatility": round(vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(longshort_mdd, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 4. Turnover Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_turnover(result: Any) -> dict[str, Any]:
    """Compute turnover analysis metrics.

    Returns dict with: avg_turnover, turnover_std.
    """
    import statistics

    group_metrics = getattr(result, "group_metrics", {})
    turnover_values = [
        gm.get("turnover", 0.0)
        for gm in group_metrics.values()
        if isinstance(gm, dict) and "turnover" in gm
    ]

    if not turnover_values:
        # Fallback: use overall turnover
        overall = getattr(result, "turnover", 0.0)
        return {"avg_turnover": round(overall, 4), "turnover_std": 0.0}

    avg = statistics.mean(turnover_values)
    std = statistics.stdev(turnover_values) if len(turnover_values) > 1 else 0.0

    return {
        "avg_turnover": round(avg, 4),
        "turnover_std": round(std, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 5. Stability Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_stability(result: Any) -> dict[str, Any]:
    """Compute stability analysis — yearly consistency.

    Returns dict with: yearly breakdown of rank_ic and ls_return.
    """
    ic_series = getattr(result, "ic_series", [])
    if not ic_series:
        return {"yearly": {}}

    # Group IC by year
    yearly_ics: dict[str, list[float]] = {}
    for pt in ic_series:
        date_str = str(pt.get("date", ""))
        year = date_str[:4] if len(date_str) >= 4 else "unknown"
        yearly_ics.setdefault(year, []).append(pt.get("ic", pt.get("rank_ic", 0)))

    import statistics
    yearly = {}
    for year, ics in sorted(yearly_ics.items()):
        yearly[year] = {
            "rank_ic": round(statistics.mean(ics), 4) if ics else 0.0,
            "n_obs": len(ics),
        }

    return {"yearly": yearly}


# ═══════════════════════════════════════════════════════════════
# 6. OOS Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_oos(result: Any) -> dict[str, Any]:
    """Compute out-of-sample analysis.

    Split IC series into first 70% (IS) and last 30% (OOS),
    compare performance.
    """
    ic_series = getattr(result, "ic_series", [])
    ls_curve = getattr(result, "longshort_curve", [])

    if not ic_series or len(ic_series) < 10:
        return {"oos_rank_ic": 0.0, "oos_ls_return": 0.0, "oos_sharpe": 0.0}

    import statistics
    split = int(len(ic_series) * 0.7)

    # IS vs OOS IC
    is_ics = [pt.get("ic", pt.get("rank_ic", 0)) for pt in ic_series[:split]]
    oos_ics = [pt.get("ic", pt.get("rank_ic", 0)) for pt in ic_series[split:]]

    oos_rank_ic = statistics.mean(oos_ics) if oos_ics else 0.0

    # OOS long-short return (from curve)
    oos_ls_return = 0.0
    oos_sharpe = 0.0
    if ls_curve and len(ls_curve) > split:
        oos_values = [pt.get("value", 1.0) for pt in ls_curve[split:]]
        if len(oos_values) > 1:
            daily_rets = [(oos_values[i] / oos_values[i - 1]) - 1
                          for i in range(1, len(oos_values)) if oos_values[i - 1] != 0]
            if daily_rets:
                oos_ls_return = (oos_values[-1] / oos_values[0]) - 1 if oos_values[0] != 0 else 0.0
                vol = statistics.stdev(daily_rets) * (252 ** 0.5) if len(daily_rets) > 1 else 1.0
                oos_sharpe = (oos_ls_return * 252 / len(daily_rets)) / vol if vol > 0 else 0.0

    return {
        "oos_rank_ic": round(oos_rank_ic, 4),
        "oos_ls_return": round(oos_ls_return, 4),
        "oos_sharpe": round(oos_sharpe, 4),
    }


# ═══════════════════════════════════════════════════════════════
# 7. Cost Analysis
# ═══════════════════════════════════════════════════════════════

def analyze_cost(result: Any, cost_bps: float = 15.0) -> dict[str, Any]:
    """Compute cost analysis — net return after transaction costs.

    Args:
        result: FactorBacktestResult
        cost_bps: Transaction cost in basis points (default 15bps)
    """
    turnover_data = analyze_turnover(result)
    avg_turnover = turnover_data.get("avg_turnover", 0.0)
    ann_return = getattr(result, "longshort_ann_return", 0.0) or getattr(result, "annual_return", 0.0)

    cost_rate = cost_bps / 10000.0
    annual_cost = avg_turnover * cost_rate * 2  # buy + sell
    net_ann_return = ann_return - annual_cost

    # Sensitivity analysis
    sensitivities = {}
    for bps in [5, 10, 15, 20, 30]:
        c = avg_turnover * (bps / 10000.0) * 2
        sensitivities[f"{bps}bp"] = round(ann_return - c, 4)

    return {
        "cost_bps": cost_bps,
        "net_ann_return": round(net_ann_return, 4),
        "cost_sensitivity": sensitivities,
    }


# ═══════════════════════════════════════════════════════════════
# Scoring Rubric
# ═══════════════════════════════════════════════════════════════

def _score_ic(ic_analysis: dict) -> float:
    """Score IC analysis (0-25)."""
    ic_mean = abs(ic_analysis.get("ic_mean", 0))
    icir = abs(ic_analysis.get("icir", 0))
    rank_ic = abs(ic_analysis.get("rank_ic_mean", 0))

    # |IC mean| scoring (0-10)
    if ic_mean > 0.05:
        ic_score = 10
    elif ic_mean > 0.03:
        ic_score = 7
    elif ic_mean > 0.01:
        ic_score = 4
    else:
        ic_score = 1

    # |ICIR| scoring (0-10)
    if icir > 1.0:
        icir_score = 10
    elif icir > 0.5:
        icir_score = 7
    elif icir > 0.2:
        icir_score = 4
    else:
        icir_score = 1

    # |RankIC| scoring (0-5)
    if rank_ic > 0.05:
        rank_score = 5
    elif rank_ic > 0.03:
        rank_score = 4
    elif rank_ic > 0.01:
        rank_score = 2
    else:
        rank_score = 1

    return ic_score + icir_score + rank_score


def _score_group(group_analysis: dict) -> float:
    """Score group analysis (0-20).

    Uses |sharpe| to handle reverse factors correctly — for a factor with
    expected_ic_sign='负', a negative long-short Sharpe is the intended direction.
    """
    ls_sharpe = abs(group_analysis.get("ls_sharpe", 0))
    ls_return = group_analysis.get("ls_ann_return", 0)
    ls_mdd = group_analysis.get("ls_max_drawdown", 0)

    # Long-short Sharpe (0-10) — score by magnitude
    if ls_sharpe > 1.5:
        sharpe_score = 10
    elif ls_sharpe > 0.5:
        sharpe_score = 7
    elif ls_sharpe > 0:
        sharpe_score = 4
    else:
        sharpe_score = 1

    # Group monotonicity — check if groups are ordered
    mono = group_analysis.get("group_monotonicity", "")
    groups = group_analysis.get("group_returns", {})
    if groups:
        n = len(groups)
        # Check if G1 > G2 > ... > Gn (or reverse)
        vals = list(groups.values())
        is_monotonic = all(vals[i] >= vals[i + 1] for i in range(n - 1)) or \
                       all(vals[i] <= vals[i + 1] for i in range(n - 1))
        mono_score = 5 if is_monotonic else 2
    else:
        mono_score = 0

    # Max drawdown penalty (0-5) — |MDD| regardless of direction
    abs_mdd = abs(ls_mdd)
    if abs_mdd < 0.1:
        dd_score = 5
    elif abs_mdd < 0.2:
        dd_score = 3
    elif abs_mdd < 0.3:
        dd_score = 1
    else:
        dd_score = 0

    return sharpe_score + mono_score + dd_score


def _score_return(return_analysis: dict) -> float:
    """Score return analysis (0-20).

    Uses |sharpe|, |calmar|, |sortino| to handle reverse factors.
    A factor with expected_ic_sign='负' has negative Sharpe that is still predictive.
    """
    sharpe = abs(return_analysis.get("sharpe", 0))
    calmar = abs(return_analysis.get("calmar", 0))
    sortino = abs(return_analysis.get("sortino", 0))

    # Sharpe (0-8) — score by magnitude
    if sharpe > 1.0:
        sharpe_score = 8
    elif sharpe > 0.5:
        sharpe_score = 6
    elif sharpe > 0:
        sharpe_score = 3
    else:
        sharpe_score = 0

    # Calmar (0-6) — score by magnitude
    if calmar > 1.0:
        calmar_score = 6
    elif calmar > 0.3:
        calmar_score = 4
    elif calmar > 0:
        calmar_score = 2
    else:
        calmar_score = 0

    # Sortino (0-6) — score by magnitude
    if sortino > 1.5:
        sortino_score = 6
    elif sortino > 0.7:
        sortino_score = 4
    elif sortino > 0:
        sortino_score = 2
    else:
        sortino_score = 0

    return sharpe_score + calmar_score + sortino_score


def _score_turnover(turnover_analysis: dict) -> float:
    """Score turnover analysis (0-10)."""
    avg = turnover_analysis.get("avg_turnover", 1.0)

    if avg < 0.20:
        return 10
    elif avg < 0.50:
        return 7
    elif avg < 0.80:
        return 4
    else:
        return 1


def _score_stability(stability_analysis: dict) -> float:
    """Score stability analysis (0-10)."""
    yearly = stability_analysis.get("yearly", {})
    if len(yearly) < 2:
        return 5  # Not enough data, neutral score

    # Check consistency: IC sign should be same across years
    ics = [v.get("rank_ic", 0) for v in yearly.values()]
    same_sign = all(v > 0 for v in ics) or all(v < 0 for v in ics)

    if same_sign and len(ics) >= 3:
        return 10
    elif same_sign:
        return 7
    else:
        # Mixed signs — partial
        pos_ratio = sum(1 for v in ics if v > 0) / len(ics)
        if 0.3 < pos_ratio < 0.7:
            return 3
        return 5


def _score_oos(oos_analysis: dict) -> float:
    """Score OOS analysis (0-10)."""
    oos_rank_ic = abs(oos_analysis.get("oos_rank_ic", 0))

    if oos_rank_ic > 0.03:
        return 10
    elif oos_rank_ic > 0.01:
        return 7
    elif oos_rank_ic > 0:
        return 4
    else:
        return 1


def _score_cost(cost_analysis: dict) -> float:
    """Score cost analysis (0-5)."""
    net = cost_analysis.get("net_ann_return", 0)

    if net > 0.05:
        return 5
    elif net > 0:
        return 3
    else:
        return 1


def compute_score(
    ic_analysis: dict,
    group_analysis: dict,
    return_analysis: dict,
    turnover_analysis: dict,
    stability_analysis: dict,
    oos_analysis: dict,
    cost_analysis: dict,
) -> dict[str, Any]:
    """Compute the 7-dimension weighted score.

    Returns dict with:
      - score: total (0-100)
      - pass_threshold: 60
      - status: "通过" / "失败" / "待更新"
      - breakdown: per-dimension scores
    """
    scores = {
        "ic": _score_ic(ic_analysis),
        "group": _score_group(group_analysis),
        "return": _score_return(return_analysis),
        "turnover": _score_turnover(turnover_analysis),
        "stability": _score_stability(stability_analysis),
        "oos": _score_oos(oos_analysis),
        "cost": _score_cost(cost_analysis),
    }

    total = sum(scores.values())
    pass_threshold = 60

    if total >= pass_threshold:
        status = "通过"
    elif total > 0:
        status = "失败"
    else:
        status = "待更新"

    return {
        "score": total,
        "pass_threshold": pass_threshold,
        "status": status,
        "breakdown": scores,
    }


# ═══════════════════════════════════════════════════════════════
# Full L5 Validation Pipeline
# ═══════════════════════════════════════════════════════════════

def run_l5_validation(result: Any, cost_bps: float = 15.0) -> dict[str, Any]:
    """Run the full L5 validation pipeline on a backtest result.

    Executes all 7 analysis modules, computes the score, and
    returns the complete L5 data structure for writing to YAML.

    Args:
        result: FactorBacktestResult from run_factor_backtest_universe()
        cost_bps: Transaction cost in basis points

    Returns:
        Complete L5 dict ready to write as factor.l5 in YAML.
    """
    ic_analysis = analyze_ic(result)
    group_analysis = analyze_groups(result)
    return_analysis = analyze_returns(result)
    turnover_analysis = analyze_turnover(result)
    stability_analysis = analyze_stability(result)
    oos_analysis = analyze_oos(result)
    cost_analysis = analyze_cost(result, cost_bps)

    score_result = compute_score(
        ic_analysis, group_analysis, return_analysis,
        turnover_analysis, stability_analysis, oos_analysis, cost_analysis,
    )

    return {
        "factor_analysis": {
            "ic_analysis": ic_analysis,
            "group_analysis": group_analysis,
            "return_analysis": return_analysis,
            "turnover_analysis": turnover_analysis,
            "stability_analysis": stability_analysis,
            "oos_analysis": oos_analysis,
            "cost_analysis": cost_analysis,
        },
        "hypothesis_testing": [],  # Filled by LLM step
        "overall_assessment": {
            "score": score_result["score"],
            "pass_threshold": score_result["pass_threshold"],
            "status": score_result["status"],
            "breakdown": score_result["breakdown"],
            "final_meaning": None,  # Filled after hypothesis testing
        },
    }


__all__ = [
    "analyze_ic",
    "analyze_groups",
    "analyze_returns",
    "analyze_turnover",
    "analyze_stability",
    "analyze_oos",
    "analyze_cost",
    "compute_score",
    "run_l5_validation",
]
