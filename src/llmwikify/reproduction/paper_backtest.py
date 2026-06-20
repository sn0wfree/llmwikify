"""Paper → Backtest Pipeline (Stage B).

Reads `quant/papers/{id}/factors/*.yaml` (output of v0.4 paper reproduction)
and runs L5 quality gate + backtest on each factor.

Design:
- Stock cross-section factors (factor_class in {momentum, volatility, ma_cross,
  rsi, value, quality, size, growth, signal_composite}): direct backtest
  via factor_backtest.run_factor_backtest_universe
- Paper-derived factors (factor_class = "formula" / subcategory = paper_derived):
  LLM-compiled Python code, runs via _compute_factor_from_code
- Industry/Macro factors (frequency != 日频): time-series correlation with
  stock returns, not standard cross-section backtest → deferred queue

Public API:
- paper_to_backtest(paper_id, work_dir, ...) -> BacktestReport
- backtest_factor(yaml_path, universe="hs300", start_date="2015-01-01", end_date="2024-12-31") -> FactorBacktestResult
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default backtest params
DEFAULT_UNIVERSE = "hs300"
DEFAULT_START_DATE = "2015-01-01"
DEFAULT_END_DATE = "2024-12-31"
DEFAULT_FORWARD_DAYS = 1
DEFAULT_N_GROUPS = 5

# L5 quality gate thresholds (Stage B-3)
L5_GATE_THRESHOLDS = {
    "ic_min": 0.02,                # IC > 0.02
    "sharpe_min": 0.5,             # Sharpe > 0.5
    "long_short_winrate_min": 0.50,  # 多空胜率 > 50%
    "max_drawdown_max": 0.20,      # 最大回撤 < 20%
    "turnover_max": 0.80,          # 换手率 < 80%
}

# Stock cross-section factor classes that have direct backtest support
STOCK_CROSS_SECTION_CLASSES = {
    "momentum", "volatility", "ma_cross", "rsi",
    "value", "quality", "size", "growth", "signal_composite",
}


@dataclass
class FactorBacktestOutcome:
    """Result of a single factor backtest."""
    factor_name: str
    yaml_path: str
    status: str  # "success" | "deferred" | "failed"
    error: str | None = None
    factor_class: str = ""
    frequency: str = ""
    l5_decision: str = "pending"  # "pass" | "needs_revision" | "reject" | "pending"
    l5_score: float = 0.0
    backtest_result: dict | None = None
    started_at: str = ""
    finished_at: str = ""


@dataclass
class PaperBacktestReport:
    """Aggregated backtest report for a paper."""
    paper_id: str
    total_factors: int = 0
    n_success: int = 0
    n_deferred: int = 0
    n_failed: int = 0
    n_pass_l5: int = 0
    n_reject_l5: int = 0
    n_needs_revision: int = 0
    factors: list[FactorBacktestOutcome] = field(default_factory=list)
    total_elapsed_min: float = 0.0
    started_at: str = ""
    finished_at: str = ""


def read_factor_yaml(yaml_path: str | Path) -> dict | None:
    """Read a factor YAML file. Returns None if invalid."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        logger.warning("YAML not found: %s", yaml_path)
        return None
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        logger.warning("YAML parse failed: %s: %s", yaml_path, exc)
        return None
    if not data or "factor" not in data:
        logger.warning("YAML missing 'factor' key: %s", yaml_path)
        return None
    return data["factor"]


def classify_factor(factor_data: dict) -> str:
    """Classify factor into backtest strategy.

    Returns one of:
        "cross_section": standard stock cross-section (direct backtest)
        "formula": LLM-compiled Python code (deferred until compiled)
        "macro_industry": industry/macro time-series (deferred)
        "unsupported": cannot be backtested (deferred)
    """
    factor_class = factor_data.get("subcategory", factor_data.get("factor_class", "")).lower()
    frequency = factor_data.get("l1", {}).get("frequency", "日频")
    category = factor_data.get("category", "").lower()

    # 1. Stock cross-section classes
    if factor_class in STOCK_CROSS_SECTION_CLASSES:
        return "cross_section"
    if factor_class == "formula":
        return "formula"
    # 2. Industry / macro / paper-derived → deferred
    if category in ("alpha", "signal", "macro", "industry"):
        if "年" in frequency or "月" in frequency or "季" in frequency:
            return "macro_industry"
        return "formula"  # Try to compile if frequency is daily
    return "unsupported"


def determine_factor_class(factor_data: dict) -> str:
    """Determine factor_class for backtest, with sensible default."""
    explicit = factor_data.get("subcategory", factor_data.get("factor_class", ""))
    if explicit:
        return explicit.lower()
    # Default heuristic: formula description with momentum keywords
    formula = factor_data.get("l1", {}).get("formula", "").lower()
    if "momentum" in formula or "动量" in formula:
        return "momentum"
    if "volatility" in formula or "波动" in formula:
        return "volatility"
    if "mean reversion" in formula or "反转" in formula or "反转因子" in formula:
        return "momentum"  # proxy
    return "momentum"  # safe default


def determine_factor_params(factor_data: dict) -> dict[str, Any]:
    """Extract factor_params from L1.default_params or L2.calculation_steps."""
    params = factor_data.get("l1", {}).get("default_params", {}) or {}
    # Common mappings
    mapped: dict[str, Any] = {}
    for k, v in params.items():
        kl = k.lower()
        if any(s in kl for s in ("period", "lookback", "window", "期", "周期")):
            try:
                mapped["period"] = int(v)
            except (TypeError, ValueError):
                pass
        elif any(s in kl for s in ("fast", "短期", "短")):
            try:
                mapped["fast"] = int(v)
            except (TypeError, ValueError):
                pass
        elif any(s in kl for s in ("slow", "长期", "长")):
            try:
                mapped["slow"] = int(v)
            except (TypeError, ValueError):
                pass
    if "period" not in mapped:
        mapped["period"] = 20
    if "fast" in mapped and "slow" not in mapped:
        mapped["slow"] = mapped.get("period", 20)
    return mapped


def paper_to_backtest(
    paper_id: str,
    work_dir: str | Path,
    universe: str = DEFAULT_UNIVERSE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    n_groups: int = DEFAULT_N_GROUPS,
    forward_days: int = DEFAULT_FORWARD_DAYS,
    l5_thresholds: dict[str, float] | None = None,
) -> PaperBacktestReport:
    """Run backtest pipeline on all factor YAMLs under work_dir/factors/.

    Args:
        paper_id: Paper identifier.
        work_dir: `quant/papers/{id}/` directory.
        universe: Stock universe label (e.g. "hs300", "csi_all").
        start_date / end_date: Backtest window.
        n_groups: Number of quantile groups.
        forward_days: Forward return period.
        l5_thresholds: Override L5 quality gate thresholds.

    Returns:
        PaperBacktestReport with per-factor outcomes + L5 decisions.
    """
    work_dir = Path(work_dir)
    factors_dir = work_dir / "factors"
    if not factors_dir.exists():
        logger.warning("No factors dir: %s", factors_dir)
        return PaperBacktestReport(paper_id=paper_id)

    if l5_thresholds is None:
        l5_thresholds = L5_GATE_THRESHOLDS

    started_at = datetime.now().isoformat()
    t0 = time.monotonic()
    report = PaperBacktestReport(
        paper_id=paper_id,
        started_at=started_at,
    )

    yaml_files = sorted(factors_dir.glob("*.yaml"))
    report.total_factors = len(yaml_files)
    logger.info("[paper_backtest] paper=%s found %d factor YAMLs", paper_id, len(yaml_files))

    for yaml_path in yaml_files:
        outcome = _backtest_one_factor(
            yaml_path=yaml_path,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            n_groups=n_groups,
            forward_days=forward_days,
            l5_thresholds=l5_thresholds,
        )
        report.factors.append(outcome)
        if outcome.status == "success":
            report.n_success += 1
        elif outcome.status == "deferred":
            report.n_deferred += 1
        else:
            report.n_failed += 1
        if outcome.l5_decision == "pass":
            report.n_pass_l5 += 1
        elif outcome.l5_decision == "reject":
            report.n_reject_l5 += 1
        elif outcome.l5_decision == "needs_revision":
            report.n_needs_revision += 1

    report.total_elapsed_min = round((time.monotonic() - t0) / 60, 2)
    report.finished_at = datetime.now().isoformat()
    logger.info(
        "[paper_backtest] paper=%s done: %d factors, %d success, %d deferred, %d failed, "
        "%d pass L5, %.1f min",
        paper_id, report.total_factors, report.n_success,
        report.n_deferred, report.n_failed, report.n_pass_l5,
        report.total_elapsed_min,
    )
    return report


def _backtest_one_factor(
    yaml_path: Path,
    universe: str,
    start_date: str,
    end_date: str,
    n_groups: int,
    forward_days: int,
    l5_thresholds: dict[str, float],
) -> FactorBacktestOutcome:
    """Backtest a single factor YAML."""
    started_at = datetime.now().isoformat()
    outcome = FactorBacktestOutcome(
        factor_name=yaml_path.stem,
        yaml_path=str(yaml_path),
        status="pending",
        started_at=started_at,
    )

    factor_data = read_factor_yaml(yaml_path)
    if factor_data is None:
        outcome.status = "failed"
        outcome.error = "YAML read failed"
        return outcome

    classification = classify_factor(factor_data)
    outcome.factor_class = factor_data.get("subcategory", factor_data.get("factor_class", ""))
    outcome.frequency = factor_data.get("l1", {}).get("frequency", "")

    if classification == "macro_industry":
        outcome.status = "deferred"
        outcome.error = f"Industry/macro factor (frequency={outcome.frequency}) not yet supported"
        outcome.l5_decision = "pending"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    if classification == "unsupported":
        outcome.status = "deferred"
        outcome.error = f"Unsupported classification (class={outcome.factor_class})"
        outcome.l5_decision = "pending"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    if classification == "formula":
        outcome.status = "deferred"
        outcome.error = "formula factor requires LLM compilation (Stage B-2)"
        outcome.l5_decision = "pending"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    # classification == "cross_section" — proceed to backtest
    factor_class = determine_factor_class(factor_data)
    factor_params = determine_factor_params(factor_data)
    outcome.factor_class = factor_class

    try:
        from .factor_backtest import run_factor_backtest_universe
        from .akshare_data import fetch_universe_data
    except ImportError as exc:
        outcome.status = "deferred"
        outcome.error = f"Required modules not available: {exc}"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    # Fetch universe data
    try:
        close_wide, tradable = fetch_universe_data(
            universe=universe,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        outcome.status = "failed"
        outcome.error = f"Data fetch failed: {exc}"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    if close_wide is None or close_wide.empty:
        outcome.status = "failed"
        outcome.error = "Empty close_wide from data fetch"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    # Run backtest
    try:
        result = run_factor_backtest_universe(
            close_wide=close_wide,
            factor_class=factor_class,
            factor_params=factor_params,
            n_groups=n_groups,
            forward_days=forward_days,
            universe=universe,
            tradable=tradable,
        )
    except Exception as exc:
        outcome.status = "failed"
        outcome.error = f"Backtest failed: {exc}"
        outcome.finished_at = datetime.now().isoformat()
        return outcome

    # L5 quality gate
    decision, score = _apply_l5_gate(result, l5_thresholds)
    outcome.l5_decision = decision
    outcome.l5_score = score
    outcome.backtest_result = _result_to_dict(result)
    outcome.status = "success"
    outcome.finished_at = datetime.now().isoformat()
    return outcome


def _apply_l5_gate(result: Any, thresholds: dict[str, float] | None = None) -> tuple[str, float]:
    """Apply L5 quality gate to backtest result.

    Returns:
        (decision, score) where decision ∈ {pass, needs_revision, reject}.
    """
    if thresholds is None:
        thresholds = L5_GATE_THRESHOLDS
    # Best-effort field extraction
    def _g(attr: str, default: float = 0.0) -> float:
        val = getattr(result, attr, None)
        if val is None and isinstance(result, dict):
            val = result.get(attr)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    ic = _g("ic_mean", _g("rank_ic_mean", 0.0))
    sharpe = _g("sharpe_ratio", _g("long_short_sharpe", 0.0))
    winrate = _g("long_short_winrate", 0.5)
    drawdown = _g("max_drawdown", 0.0)
    turnover = _g("turnover", _g("avg_turnover", 0.0))

    # Composite score (0-1)
    score = 0.0
    n_checks = 5
    if ic > thresholds["ic_min"]:
        score += 1
    if sharpe > thresholds["sharpe_min"]:
        score += 1
    if winrate > thresholds["long_short_winrate_min"]:
        score += 1
    if drawdown < thresholds["max_drawdown_max"]:
        score += 1
    if turnover < thresholds["turnover_max"]:
        score += 1
    score = score / n_checks

    # Decision
    if score >= 0.6:
        decision = "pass"
    elif score >= 0.4:
        decision = "needs_revision"
    else:
        decision = "reject"
    return decision, round(score, 3)


def _result_to_dict(result: Any) -> dict | None:
    """Convert FactorBacktestResult to dict, dropping non-serialisable fields."""
    if result is None:
        return None
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dict__"):
        return {k: v for k, v in vars(result).items()
                if isinstance(v, (int, float, str, bool, list, dict, type(None)))}
    return None


def save_report(report: PaperBacktestReport, work_dir: Path) -> None:
    """Save report as JSON under work_dir/backtest_results.json."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "backtest_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)
    logger.info("[paper_backtest] saved %s", out_path)


__all__ = [
    "L5_GATE_THRESHOLDS",
    "STOCK_CROSS_SECTION_CLASSES",
    "FactorBacktestOutcome",
    "PaperBacktestReport",
    "classify_factor",
    "paper_to_backtest",
    "read_factor_yaml",
    "save_report",
]
