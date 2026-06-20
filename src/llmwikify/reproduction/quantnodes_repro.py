"""QuantNodes 通用复现框架 (Stage B: 直接用 QuantNodes).

直接用 QuantNodes PipelineRunner + LoadDataNode + ICAnalyzer 跑因子回测。
factor YAML → SingleFactorTestConfig → PipelineRunner.run() → ctx → 报告。

Public API:
- run_factor_backtest(factor_yaml_path, data_path, ...) -> BacktestOutcome
- run_paper_backtest(paper_id, work_dir, data_path, ...) -> PaperBacktestReport
"""
from __future__ import annotations

import json
import logging
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# L5 quality gate thresholds (multi-dimensional)
L5_GATE_THRESHOLDS = {
    "ic_min": 0.02,
    "sharpe_min": 0.5,
    "winrate_min": 0.50,
    "max_drawdown_max": 0.20,
    "turnover_max": 0.80,
}


@dataclass
class BacktestOutcome:
    factor_name: str
    status: str  # "success" | "deferred" | "failed"
    error: str | None = None
    compiled_expression: str = ""
    new_operators: list[str] = field(default_factory=list)
    l5_decision: str = "pending"  # "pass" | "needs_revision" | "reject" | "pending"
    l5_score: float = 0.0
    metrics: dict = field(default_factory=dict)
    elapsed_sec: float = 0.0


@dataclass
class PaperBacktestReport:
    paper_id: str
    total_factors: int = 0
    n_success: int = 0
    n_deferred: int = 0
    n_failed: int = 0
    n_pass_l5: int = 0
    n_reject_l5: int = 0
    n_needs_revision: int = 0
    factors: list[BacktestOutcome] = field(default_factory=list)
    total_elapsed_min: float = 0.0
    started_at: str = ""
    finished_at: str = ""


def _read_factor_yaml(yaml_path: str | Path) -> dict | None:
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return None
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        logger.warning("YAML parse failed: %s: %s", yaml_path, exc)
        return None
    if not data or "factor" not in data:
        return None
    return data["factor"]


def _build_pipeline_config(
    factor_name: str,
    expression: str,
    data_path: str,
    sample_index: str = "HS300",
    start_yyyymmdd: int = 20200101,
    end_yyyymmdd: int = 20241231,
) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner.from_dict."""
    return {
        "factor": {
            "name": factor_name,
            "factor_dir": data_path,
            "factor_key": "factor_value",
            "format": "csv",
            "expression": expression,
        },
        "preprocess": {
            "adj_date_beg": start_yyyymmdd,
            "adj_date_end": end_yyyymmdd,
            "adj_mode": ["M", "end"],
            "sample_index": sample_index,
            "sample_industry": "all",
            "tradable": {
                "no_st": True,
                "no_suspended": True,
                "no_up_down_limit": False,
                "min_ipo_days": 60,
            },
            "missing": "",
            "extreme": "median",
            "norm": "zscore",
        },
        "analysis": {
            "ic": {"min_group_size": 5},
            "group": {"groups": 5, "factor_direction": 1, "hedge": "equal"},
            "longshort": {"factor_direction": 1},
        },
        "data_path": data_path,
        "load_keys": [
            "stklist", "trade_dt", "cp", "id_citic1",
            "mv_float", "st", "suspend", "ud_limit", "ipo_days",
        ],
    }


def _extract_metrics(ctx: dict) -> dict:
    """Extract IC / group / longshort metrics from PipelineRunner.run() ctx.

    Prefers FactorTestReport (aggregate) over individual nodes.
    """
    metrics: dict = {}
    # Preferred: FactorTestReport aggregate
    report = ctx.get("FactorTestReport") or {}
    if isinstance(report, dict):
        ic = report.get("ic") or {}
        group = report.get("group") or {}
        ls = report.get("longshort") or {}
        score = report.get("score") or {}
        # IC metrics
        if isinstance(ic, dict):
            for k in ("ic_mean", "ic_std", "icir", "rank_ic_mean", "rank_ic_std"):
                if k in ic:
                    metrics[k] = ic[k]
        # Group metrics
        if isinstance(group, dict):
            for k in ("group_returns", "long_short_return", "long_short_sharpe",
                      "long_short_winrate", "max_drawdown", "turnover"):
                if k in group:
                    metrics[k] = group[k]
        # LongShort metrics
        if isinstance(ls, dict):
            for k in ("sharpe", "annualized_return", "max_drawdown", "winrate", "turnover"):
                if k in ls:
                    metrics.setdefault(f"ls_{k}", ls[k])
        # Score metrics (FactorScore node)
        if isinstance(score, dict):
            for k in ("eva", "eva_yearly", "fac_group"):
                if k in score:
                    metrics.setdefault(f"score_{k}", score[k])

    # Fallback: individual nodes
    if not metrics:
        ic = ctx.get("ICAnalyzer") or {}
        if isinstance(ic, dict):
            for k in ("ic_mean", "ic_std", "icir", "rank_ic_mean", "rank_ic_std"):
                if k in ic and isinstance(ic[k], (int, float)):
                    metrics[k] = ic[k]
        group = ctx.get("GroupAnalyzer") or {}
        if isinstance(group, dict):
            for k in ("group_ret", "group_winratio"):
                if k in group and isinstance(group[k], (int, float)):
                    metrics.setdefault(k, group[k])
        ls = ctx.get("LongShort") or {}
        if isinstance(ls, dict):
            for k in ("eva_total",):
                if k in ls and isinstance(ls[k], (int, float)):
                    metrics.setdefault(f"ls_{k}", ls[k])
    return metrics


def _apply_l5_gate(metrics: dict, thresholds: dict | None = None) -> tuple[str, float]:
    """Apply multi-dim L5 quality gate to backtest metrics."""
    if thresholds is None:
        thresholds = L5_GATE_THRESHOLDS

    def _g(key: str, default: float = 0.0) -> float:
        v = metrics.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    ic = _g("ic_mean", _g("rank_ic_mean", 0.0))
    sharpe = _g("ls_sharpe", _g("long_short_sharpe", 0.0))
    winrate = _g("ls_winrate", _g("long_short_winrate", 0.5))
    drawdown = _g("ls_max_drawdown", _g("max_drawdown", 0.0))
    turnover = _g("ls_turnover", _g("turnover", 0.0))

    score = 0.0
    if ic > thresholds["ic_min"]:
        score += 1
    if sharpe > thresholds["sharpe_min"]:
        score += 1
    if winrate > thresholds["winrate_min"]:
        score += 1
    if drawdown < thresholds["max_drawdown_max"]:
        score += 1
    if turnover < thresholds["turnover_max"]:
        score += 1
    score = score / 5.0

    if score >= 0.6:
        decision = "pass"
    elif score >= 0.4:
        decision = "needs_revision"
    else:
        decision = "reject"
    return decision, round(score, 3)


def run_factor_backtest(
    factor_yaml_path: str | Path,
    data_path: str,
    sample_index: str = "HS300",
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    use_cache: bool = True,
) -> BacktestOutcome:
    """Run a single factor backtest via QuantNodes PipelineRunner.

    Pipeline:
    1. Read factor YAML
    2. Compile formula via FactorCompiler (LLM + CustomOperator for new ops)
    3. Execute compiled expression on cached data → DataFrame (cross-section)
    4. Save as H5/CSV (QuantNodes LoadDataNode expected format)
    5. Build SingleFactorTestConfig with factor_dir = saved file
    6. PipelineRunner.from_dict(config).run()
    7. Extract metrics + apply L5 gate

    Args:
        factor_yaml_path: Path to factor YAML.
        data_path: Path to QuantNodes-compatible OHLCV HDF5 dir.
        sample_index: 'HS300' / 'ZZ500' / 'all'.
        start_date: ISO date string.
        end_date: ISO date string.
        use_cache: Reuse compiled code cache.

    Returns:
        BacktestOutcome with metrics, L5 decision, status.
    """
    from .factor_compiler import FactorCompiler
    from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner

    t0 = time.monotonic()
    yaml_path = Path(factor_yaml_path)
    outcome = BacktestOutcome(factor_name=yaml_path.stem, status="pending")

    # Step 1: Read factor YAML
    factor_data = _read_factor_yaml(yaml_path)
    if factor_data is None:
        outcome.status = "failed"
        outcome.error = "YAML read failed"
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    # Step 2: Compile formula via LLM
    compiler = FactorCompiler()
    try:
        compile_result = compiler.compile(factor_data, use_cache=use_cache)
    except Exception as exc:
        outcome.status = "failed"
        outcome.error = f"Compile exception: {exc}"
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    if not compile_result.is_valid or not compile_result.code:
        outcome.status = "deferred"
        outcome.error = compile_result.error_message or "code invalid"
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    outcome.compiled_expression = compile_result.code
    outcome.new_operators = compile_result.new_operators

    # Step 3: Execute compiled expression on cached data → DataFrame
    try:
        factor_df = _execute_compiled_expression(
            expression=compile_result.code,
            data_path=data_path,
            factor_name=yaml_path.stem,
        )
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        outcome.status = "failed"
        outcome.error = f"Execute compiled: {type(exc).__name__}: {exc}\n{tb[-800:]}"
        logger.exception("Execute compiled failed")
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    # Step 4: Save factor to H5 (QuantNodes LoadDataNode format)
    import pandas as pd
    factor_file = Path(data_path) / f"factor_{yaml_path.stem}.h5"
    try:
        with pd.HDFStore(factor_file, mode="w") as store:
            store.put(yaml_path.stem, factor_df)
    except Exception as exc:
        outcome.status = "failed"
        outcome.error = f"Save factor: {type(exc).__name__}: {exc}"
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    # Step 5: Build config
    start_yyyymmdd = int(start_date.replace("-", ""))
    end_yyyymmdd = int(end_date.replace("-", ""))
    config = _build_pipeline_config(
        factor_name=factor_data.get("name", yaml_path.stem),
        expression=compile_result.code,
        data_path=data_path,
        sample_index=sample_index,
        start_yyyymmdd=start_yyyymmdd,
        end_yyyymmdd=end_yyyymmdd,
    )
    # factor_dir is just the filename (DataLoader joins with data_path)
    config["factor"]["factor_dir"] = factor_file.name
    config["factor"]["factor_key"] = yaml_path.stem
    config["factor"]["format"] = "h5"

    # Step 6: Run PipelineRunner
    try:
        runner = PipelineRunner.from_dict(config)
        ctx = runner.run()
    except Exception as exc:
        outcome.status = "failed"
        outcome.error = f"PipelineRunner: {type(exc).__name__}: {exc}"
        outcome.elapsed_sec = time.monotonic() - t0
        return outcome

    # Step 7: Extract metrics + L5 gate
    outcome.metrics = _extract_metrics(ctx)
    decision, score = _apply_l5_gate(outcome.metrics)
    outcome.l5_decision = decision
    outcome.l5_score = score
    outcome.status = "success"
    outcome.elapsed_sec = time.monotonic() - t0
    return outcome


def _execute_compiled_expression(
    expression: str,
    data_path: str,
    factor_name: str,
) -> Any:
    """Execute LLM-compiled QuantNodes polars expression on cached data.

    Returns:
        DataFrame indexed by date with code columns (= [date × code] wide format).
    """
    import pandas as pd
    import polars as pl
    import numpy as np

    data_path = Path(data_path)
    # Load stk_daily.h5 keys
    cp_wide = pd.read_hdf(data_path / "stk_daily.h5", "cp")
    open_wide = pd.read_hdf(data_path / "stk_daily.h5", "open")
    high_wide = pd.read_hdf(data_path / "stk_daily.h5", "high")
    low_wide = pd.read_hdf(data_path / "stk_daily.h5", "low")
    close_wide = cp_wide
    volume_wide = pd.read_hdf(data_path / "stk_daily.h5", "volume")
    returns_wide = pd.read_hdf(data_path / "stk_daily.h5", "returns")
    vwap_wide = pd.read_hdf(data_path / "stk_daily.h5", "vwap")

    # Convert to polars (date index → column, code columns → long format)
    def wide_to_polars(wide: pd.DataFrame, value_name: str) -> pl.DataFrame:
        long = wide.stack().reset_index()
        long.columns = ["date", "code", value_name]
        return pl.from_pandas(long)

    df_pl = (
        wide_to_polars(close_wide, "close")
        .join(wide_to_polars(open_wide, "open"), on=["date", "code"])
        .join(wide_to_polars(high_wide, "high"), on=["date", "code"])
        .join(wide_to_polars(low_wide, "low"), on=["date", "code"])
        .join(wide_to_polars(volume_wide, "volume"), on=["date", "code"])
        .join(wide_to_polars(returns_wide, "returns"), on=["date", "code"])
        .join(wide_to_polars(vwap_wide, "vwap"), on=["date", "code"])
    )

    # Build namespace for exec
    namespace = {
        "pl": pl,
        "polars": pl,
        "np": np,
        "pd": pd,
        "close": "close",
        "open": "open",
        "high": "high",
        "low": "low",
        "volume": "volume",
        "returns": "returns",
        "vwap": "vwap",
    }

    # Strip markdown
    import re
    expr_clean = re.sub(r"```python\n", "", expression)
    expr_clean = re.sub(r"```\n?", "", expr_clean)

    # Column names to auto-wrap as pl.col() — but only when they appear
    # in polars expressions (not inside string literals or function calls).
    COL_NAMES = ["close", "open", "high", "low", "volume", "returns", "vwap"]

    def col_pat(name: str) -> re.Pattern:
        # Match the bare identifier NOT preceded by . (attribute access) and
        # NOT followed by ( (function call). e.g. match 'close' in
        # 'rank(close)' but not in 'pl.col(close)' or 'something.close'.
        return re.compile(rf"(?<![\w.]){name}(?![\w(])")

    for name in COL_NAMES:
        expr_clean = col_pat(name).sub(f"pl.col('{name}')", expr_clean)

    # Execute expression (last line should be the result)
    local_ns = {"pl": pl, "polars": pl, "np": np, "pd": pd}
    # Provide all QuantNodes operators in namespace
    try:
        from QuantNodes.operators.proxy import _OPERATOR_REGISTRY
        for category_ops in _OPERATOR_REGISTRY.values():
            for op_name, op_info in category_ops.items():
                local_ns[op_name] = op_info["func"]
    except Exception:
        pass

    result = eval(expr_clean, {"__builtins__": {}}, local_ns)

    # Compute the factor: add as a column to df_pl
    if isinstance(result, pl.Expr):
        df_with_factor = df_pl.with_columns(result.alias("factor_value"))
    else:
        # Result is a scalar
        df_with_factor = df_pl.with_columns(pl.lit(float(result)).alias("factor_value"))

    # Pivot to wide format [date × code]
    factor_pandas = df_with_factor.select(["date", "code", "factor_value"]).to_pandas()
    factor_wide = factor_pandas.pivot(index="date", columns="code", values="factor_value")
    factor_wide.index = pd.to_datetime(factor_wide.index)
    return factor_wide


def run_paper_backtest(
    paper_id: str,
    work_dir: str | Path,
    data_path: str,
    sample_index: str = "HS300",
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    factor_names: list[str] | None = None,
    use_cache: bool = True,
) -> PaperBacktestReport:
    """Run backtest on all factor YAMLs under work_dir/factors/.

    Args:
        paper_id: Paper identifier.
        work_dir: `quant/papers/{id}/` directory.
        data_path: Path to QuantNodes-compatible OHLCV CSV/Parquet.
        sample_index: 'HS300' / 'ZZ500' / 'all'.
        start_date: ISO date.
        end_date: ISO date.
        factor_names: Optional list to subset (default: all).
        use_cache: Reuse compiled code cache.

    Returns:
        PaperBacktestReport with per-factor outcomes.
    """
    work_dir = Path(work_dir)
    factors_dir = work_dir / "factors"
    report = PaperBacktestReport(
        paper_id=paper_id,
        started_at=datetime.now().isoformat(),
    )

    if not factors_dir.exists():
        logger.warning("No factors dir: %s", factors_dir)
        return report

    t0 = time.monotonic()
    yaml_files = sorted(factors_dir.glob("*.yaml"))
    if factor_names:
        yaml_files = [p for p in yaml_files if p.stem in factor_names]
    report.total_factors = len(yaml_files)
    logger.info("[quantnodes_repro] paper=%s found %d factors", paper_id, len(yaml_files))

    for yaml_path in yaml_files:
        outcome = run_factor_backtest(
            factor_yaml_path=yaml_path,
            data_path=data_path,
            sample_index=sample_index,
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache,
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
        logger.info(
            "[quantnodes_repro] %s: status=%s, l5=%s(%.2f), %.1fs",
            outcome.factor_name, outcome.status,
            outcome.l5_decision, outcome.l5_score, outcome.elapsed_sec,
        )

    report.total_elapsed_min = round((time.monotonic() - t0) / 60, 2)
    report.finished_at = datetime.now().isoformat()
    logger.info(
        "[quantnodes_repro] paper=%s done: %d/%d success, %d deferred, %d failed, "
        "%d pass L5, %.1f min",
        paper_id, report.n_success, report.total_factors,
        report.n_deferred, report.n_failed, report.n_pass_l5, report.total_elapsed_min,
    )
    return report


def save_report(report: PaperBacktestReport, work_dir: Path) -> None:
    """Save report as JSON under work_dir/backtest_results.json."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "backtest_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)
    logger.info("[quantnodes_repro] saved %s", out_path)


__all__ = [
    "L5_GATE_THRESHOLDS",
    "BacktestOutcome",
    "PaperBacktestReport",
    "run_factor_backtest",
    "run_paper_backtest",
    "save_report",
]
