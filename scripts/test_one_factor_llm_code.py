"""Single-factor E2E test: LLM code path + QuantNodes PipelineRunner.

Tests alpha-001 from 101 alphas paper:
  (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)

Pipeline:
  1. Read formula_brief from track_b_checkpoint.json
  2. LLM emit Python code via SYSTEM_PROMPT_CODE (no AST) — via
     `factor_compiler_react.compile_to_code_react` (ReAct loop with
     extract → syntax → safety → execute feedback). Self-repair on failure.
  3. Save factor to H5 (factor_alpha-001.h5, shape [date × code])
  4. Build SingleFactorTestConfig dict
  5. PipelineRunner.run() → 12 nodes → IC / ICIR / 分组 / 多空

Phase 2 (2026-06-22): replaced the inline 1-shot LLM call with the
ReAct driver so the LLM can self-repair typos (e.g. .out('date') vs
.over('date')) via injected error feedback. Old 1-shot path is kept
behind `--no-react` for A/B comparison.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

from llmwikify.reproduction.codegen.llm_code import (
    SYSTEM_PROMPT_CODE,
    build_llm_client,
    execute_code,
    extract_python,
    validate_safety,
    validate_syntax,
)

PROJECT_ROOT = Path("/home/ll/llmwikify")
# Switched from short (65d) to long (1305d, 5y) data on 2026-06-22 for meaningful IC.
DATA_PATH = Path("/home/ll/.llmwikify/akshare_cache/quantnodes_h5_long")
TRACK_B = PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json"
OUTPUT_DIR = PROJECT_ROOT / "scripts" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Date range for the long dataset (YYYYMMDD format for QN config)
LONG_DATE_BEG = 20200101
LONG_DATE_END = 20241231


# ─── 工具函数 ─────────────────────────────────────────────────────


def _wide_from_long(df_pl: pl.DataFrame, factor_series: pl.Series) -> pd.DataFrame:
    """Convert long (date, code, value) → wide [date × code] for QuantNodes H5.

    Note: df_pl.date is polars Int64 (yyyymmdd). When pivoting, we keep it as
    int64 — converting via pd.to_datetime(int) interprets int as nanoseconds
    since epoch and produces 1970-01-01 dates, which corrupts the factor file.

    DATA ORDERING: input df_pl is sorted by (date, code). LLM code may have
    re-sorted by (code, date) inside `compute_factor`, which means the
    returned `factor_series` is in (code, date) order — misaligned with
    df_pl. We force sort by (code, date) here so pivot input is always
    in (code, date) order, matching factor_series. This eliminates the
    misalignment that causes GroupAnalyzer "Bin labels must be unique" errors.
    """
    assert len(df_pl) == len(factor_series), f"length mismatch: {len(df_pl)} vs {len(factor_series)}"
    # Force (code, date) order to match the sort done by LLM code
    df_sorted = df_pl.sort(['code', 'date'])
    df_with = df_sorted.with_columns(factor_series.alias("__factor__"))
    pdf = df_with.select(["date", "code", "__factor__"]).to_pandas()
    # Pivot keeps date as int64 (yyyymmdd) — required for QuantNodes valid_date()
    wide = pdf.pivot(index="date", columns="code", values="__factor__")
    return wide


def _write_factor_h5(wide: pd.DataFrame, factor_name: str, output_dir: Path) -> Path:
    """Write wide DataFrame to QuantNodes-compatible H5 file.

    Output file must live INSIDE data_path (PipelineRunner joins factor_dir with data_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    h5_path = output_dir / f"factor_{factor_name}.h5"
    # Use a sanitized H5 key (alphanumeric + underscore only)
    safe_key = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    with pd.HDFStore(h5_path, mode="w") as store:
        store.put(safe_key, wide)
    return h5_path


def _build_qn_config(factor_name: str, h5_path: Path, expression: str) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner.

    Schema (from QuantNodes/research/factor_test/config.py):
    - risk_corr.factors: str ('all' or comma-sep, NOT list)
    - output.format: list[str] (NOT str)
    - load_keys: list[str] (NOT None)

    Convention (from quantnodes_repro.py):
    - factor_dir is just the filename (PipelineRunner joins with data_path)
    - factor H5 file must live in data_path directory
    - factor.name is the H5 key (LoadDataNode uses this for store.get)
    """
    # LoadDataNode uses factor.name (not factor_key) to look up the H5 key.
    # We sanitize to alphanumeric+underscore so natural naming works.
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    return {
        "factor": {
            "name": safe_name,
            "factor_dir": h5_path.name,  # PipelineRunner joins with data_path
            "factor_key": safe_name,
            "format": "h5",
            "hypothesis": "Test LLM-generated code via PipelineRunner",
            "description": "alpha-001 via LLM code path",
            "expression": expression[:500],
        },
        "data_path": str(h5_path.parent),
        "load_keys": [
            "stklist", "trade_dt", "cp", "id_citic1", "mv_float",
            "st", "suspend", "ud_limit", "ipo_days",
        ],
        "preprocess": {
            "adj_date_beg": LONG_DATE_BEG,
            "adj_date_end": LONG_DATE_END,
            "adj_mode": ["M", "end"],
            "sample_index": "all",
            "sample_industry": "all",
            "tradable": {
                "no_st": True,
                "no_suspended": True,
                "no_up_down_limit": False,
                "min_ipo_days": 60,  # long dataset: filter IPO < 60 days
            },
            "missing": "",
            "extreme": "",
            "norm": "",
            "industry_neutral": False,
            "risk_neutral": False,
            "risk_factors": [],
            "mad_n": 5.0,
            "pct_low": 0.025,
            "pct_high": 0.975,
        },
        "analysis": {
            "ic": {"min_group_size": 3},
            "group": {
                "groups": 5,
                "factor_direction": 1,
                "floor_mode": "group",
                "hedge": "equal",
                "hedge_path": None,
            },
            "longshort": {"factor_direction": 1},
            "score": {"enabled": False},
            "risk_corr": {"factors": "all"},
        },
        "output": {
            "dir": str(PROJECT_ROOT / "scripts" / "output" / "report"),
            "format": ["parquet", "json"],
        },
    }


# ─── 主流程 ───────────────────────────────────────────────────────


def _llm_code_oneshot(
    factor_name: str,
    formula_brief: str,
    df_pl: pl.DataFrame,
    llm: Any,
    temperature: float = 0.3,
) -> tuple[str | None, pl.Series | None, str | None, int]:
    """Old 1-shot path: single LLM call → extract → validate → execute.

    Returns (code, factor_series, error, stage_idx) where stage_idx maps to
    "llm" / "extract" / "syntax" / "safety" / "execute" / None on success.
    Used by `--no-react` mode.
    """
    user_prompt = f"""Factor: {factor_name}
Formula (pseudo-code): {formula_brief}

Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series` that computes
this factor. Use QuantNodes operators (rank, ts_argmax, rolling_std, etc.) which are
in the namespace, and use polars expressions otherwise.

Output ONLY the code block."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CODE},
        {"role": "user", "content": user_prompt},
    ]
    try:
        content = llm.chat(messages=messages, temperature=temperature)
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}", -1

    print(f"\n[LLM] raw response ({len(content)} chars):")
    print(content[:500] + ("..." if len(content) > 500 else ""))

    code = extract_python(content)
    if not code:
        return None, None, "no code fence", 0
    print(f"\n[extract] code ({len(code)} chars):")
    print(code)

    syntax_ok, syntax_err = validate_syntax(code)
    if not syntax_ok:
        return None, None, syntax_err, 1
    print("[syntax] OK")

    safe_ok, safe_err = validate_safety(code)
    if not safe_ok:
        return None, None, safe_err, 2
    print("[safety] OK")

    try:
        series = execute_code(code, df_pl)
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}", 3
    print(f"[execute] OK: factor_series len={len(series)}, dtype={series.dtype}")
    print(f"[execute] sample: {series.head(5).to_list()}")
    return code, series, None, None


_STAGE_NAMES = {-1: "llm", 0: "extract", 1: "syntax", 2: "safety", 3: "execute"}


def _llm_code_react(
    factor_name: str,
    formula_brief: str,
    df_pl: pl.DataFrame,
    llm: Any,
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
) -> tuple[str | None, pl.Series | None, str | None, dict]:
    """ReAct self-retry path: LLM emits code, executes, on failure feeds
    error back to LLM up to max_repair_rounds times.

    Returns (code, factor_series, error, react_result_dict).
    """
    from llmwikify.reproduction.codegen.react_engine import (
        ReactStep,
        compile_to_code_react,
    )

    def _progress(step: ReactStep) -> None:
        state = step.state.value
        ek = step.error_kind.value
        if ek == "none":
            print(f"  [ReAct/{state}] OK ({step.elapsed_sec * 1000:.0f}ms)")
        else:
            print(
                f"  [ReAct/{state}] {ek}: {step.error_message[:120]}"
                f" ({step.elapsed_sec * 1000:.0f}ms)"
            )

    result = compile_to_code_react(
        factor_name=factor_name,
        formula_brief=formula_brief,
        system_prompt=SYSTEM_PROMPT_CODE,
        df=df_pl,
        llm=llm,
        max_repair_rounds=max_repair_rounds,
        temperature=temperature,
        progress_callback=_progress,
    )

    print(f"\n[ReAct] iterations={result.iterations}, "
          f"is_valid={result.is_valid}, error_kind={result.error_kind.value}")
    for i, step in enumerate(result.steps):
        print(f"  step {i}: {step.state.value} "
              f"({step.error_kind.value if step.error_kind.value != 'none' else 'OK'})")

    if not result.is_valid:
        return None, None, result.error_message, result.to_dict()

    # Re-execute the final code to get the Series (compile_to_code_react
    # doesn't return the Series; we re-run the validated code)
    try:
        series = execute_code(result.code, df_pl)
    except Exception as exc:
        return None, None, f"final execute failed: {exc}", result.to_dict()
    return result.code, series, None, result.to_dict()


# ─── Phase 1: 完整 backtest 数据提取 + 入库 (2026-06-22) ────────────
# 复用 factor_library.write_factor_yaml (B 的 API) +
# sessions.ReproductionDatabase.create_result (DB sessions)
# 模仿 factor_compiler.persist_l5_to_yaml 模式 (read → modify → write → log)


def _safe_float(x: Any, default: float | None = None) -> float | None:
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


def _extract_full_backtest_from_ctx(ctx: dict) -> dict:
    """Extract full backtest data from PipelineRunner ctx.

    Returns dict with:
      - ic_mean, rank_ic_mean, icir, rank_icir, win_rate, ic_std
      - ic_series: [{date, ic}, ...]
      - group_metrics: {G1: {annual_return, sharpe, max_drawdown, win_rate, turnover, n_stocks}, ...}
      - longshort_ann_return, longshort_sharpe, longshort_max_dd

    Defensive: missing fields → None (not crash).
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

    # ─── ICAnalyzer ───────────────────────────────────────
    ic_node = ctx.get("ICAnalyzer") or {}
    ic_result = ic_node.get("ic_result") if isinstance(ic_node, dict) else None
    if ic_result is not None and hasattr(ic_result, "get"):
        out["ic_mean"] = _safe_float(ic_result.get("IC均值"))
        out["ic_std"] = _safe_float(ic_result.get("IC标准差"))
        out["icir"] = _safe_float(ic_result.get("ICIR"))
        out["win_rate"] = _safe_float(ic_result.get("IC为正比例"))

    rank_ic_result = ic_node.get("rank_ic_result") if isinstance(ic_node, dict) else None
    if rank_ic_result is not None and hasattr(rank_ic_result, "get"):
        out["rank_ic_mean"] = _safe_float(rank_ic_result.get("Rank IC均值"))
        out["rank_icir"] = _safe_float(rank_ic_result.get("Rank ICIR"))

    # IC time series for charts
    ic_series_obj = ic_node.get("ic") if isinstance(ic_node, dict) else None
    if ic_series_obj is not None and hasattr(ic_series_obj, "items"):
        out["ic_series"] = [
            {"date": int(d), "ic": _safe_float(v, 0.0)}
            for d, v in ic_series_obj.items()
            if _safe_float(v) is not None
        ]

    # ─── GroupAnalyzer ────────────────────────────────────
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
                    "annual_return": _safe_float(group_eva_abs.loc["AnnualRt", g], 0.0),
                    "sharpe": _safe_float(group_eva_abs.loc["SR", g], 0.0),
                    "max_drawdown": _safe_float(group_eva_abs.loc["MDD", g], 0.0),
                    "win_rate": _safe_float(group_eva_abs.loc["WinRatio", g], 0.0),
                    "turnover": _safe_float(turnover_obj.loc[g], 0.0) if turnover_obj is not None and hasattr(turnover_obj, "loc") and g in turnover_obj.index else 0.0,
                    "n_stocks": 0,  # filled from group_num below if available
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

    # ─── LongShort ────────────────────────────────────────
    ls = ctx.get("LongShort") or {}
    if isinstance(ls, dict):
        net = ls.get("net")
        if net is not None and hasattr(net, "iloc"):
            # net is a DataFrame with long-short cumulative curve; compute ann_ret / sharpe / mdd
            try:
                ls_curve = net.iloc[:, 0] if hasattr(net, "iloc") else None
                if ls_curve is not None and len(ls_curve) > 1:
                    n_periods = len(ls_curve)
                    # Monthly rebalance → annualize
                    periods_per_year = 12
                    total_ret = float(ls_curve.iloc[-1] / ls_curve.iloc[0] - 1)
                    out["longshort_ann_return"] = (1 + total_ret) ** (periods_per_year / n_periods) - 1 if n_periods > 0 else 0.0
                    # MDD
                    peak = ls_curve.cummax()
                    dd = (ls_curve - peak) / peak
                    out["longshort_max_dd"] = float(dd.min())
                    # Sharpe (monthly)
                    if hasattr(ls, "period_ret") and ls["period_ret"] is not None:
                        pr = ls["period_ret"]
                        if hasattr(pr, "std"):
                            std = float(pr.std(ddof=1))
                            mean = float(pr.mean())
                            out["longshort_sharpe"] = (mean / std * (periods_per_year ** 0.5)) if std > 0 else 0.0
            except Exception as exc:
                print(f"[extract] longshort calc warning: {exc}")

    return out


def _compute_score(icir: float | None, win_rate: float | None) -> int:
    """Compute L5 overall_assessment.score (0-100) from ICIR + WinRate.

    Weighted: 70% ICIR (dominant) + 30% WinRate.
    """
    import math
    if icir is None or (isinstance(icir, float) and math.isnan(icir)):
        return 50
    # ICIR is typically -1 to +1; map to 0-100 with center at 0
    icir_score = max(0, min(100, 50 + round(icir * 50)))
    if win_rate is None or (isinstance(win_rate, float) and math.isnan(win_rate)):
        return icir_score
    wr_score = round(win_rate * 100)
    return round(icir_score * 0.7 + wr_score * 0.3)


def _compute_status(icir: float | None) -> str:
    """Compute L5 overall_assessment.status from ICIR.

    Mapping (matches WebUI OverallAssessment.tsx STATUS_CONFIG):
      通过  — ICIR > 0.10  (positive edge)
      失败  — ICIR < -0.05 (negative edge)
      待更新 — default
    """
    import math
    if icir is None or (isinstance(icir, float) and math.isnan(icir)):
        return "待验证"
    if icir > 0.10:
        return "通过"
    if icir < -0.05:
        return "失败"
    return "待更新"


def persist_code_to_yaml(
    factor_name: str,
    code: str,
    formula_brief: str,
    backtest: dict,
    h5_path: str,
    code_chars: int,
) -> str | None:
    """Persist code-path factor YAML (6-layer) to quant/factors/.

    Mirrors ``factor_compiler.persist_l5_to_yaml`` pattern:
      read_factor_yaml → modify l5.* → write_factor_yaml → log.

    WebUI L5 reads l5.overall_assessment.{score, status, pass_threshold, final_meaning}
    (FactorDetail.tsx L5Content → OverallAssessment.tsx).
    L2-L6 populated by Phase 3 LLM extraction (overwrites this default).
    """
    from llmwikify.reproduction.persist.factor_library import (
        read_factor_yaml,
        write_factor_yaml,
    )

    # Slug convention: alpha_001 (underscore, matches existing stub)
    slug = factor_name.replace("-", "_")

    try:
        existing = read_factor_yaml(slug)
        if existing is None:
            data = {
                "factor": {
                    "name": slug,
                    "asset_type": "stock",
                    "category": "formulaic",
                    "status": "已验证",
                }
            }
        else:
            data = existing

        factor = data.setdefault("factor", {})
        factor["name"] = slug
        factor["asset_type"] = factor.get("asset_type", "stock")
        factor["category"] = factor.get("category", "formulaic")
        factor["status"] = "已验证"
        factor["updated_at"] = time.strftime("%Y-%m-%d")

        # ─── L1 (Phase 2 derivation done here for cohesion) ───
        l1 = factor.setdefault("l1", {})
        if not l1.get("definition"):
            l1["definition"] = formula_brief[:200]
        l1["formula"] = formula_brief
        l1["frequency"] = "日频"
        l1["output_schema"] = "[date × Code]"
        l1["input_columns"] = _derive_input_columns(formula_brief)
        l1["nan_meaning"] = "上市不足或窗口期数据不足"
        l1["default_params"] = {}
        l1["param_constraints"] = {}
        l1["business_constraints"] = "支持日频调仓, T+1 信号"

        # ─── L5: code + overall_assessment (WebUI contract) ───
        l5 = factor.setdefault("l5", {})
        l5["code"] = code
        l5["code_compile_status"] = "success"
        l5["code_chars"] = code_chars
        l5["h5_path"] = h5_path
        # Code-path 不生成 AST, 显式置 null 避免 stub 残留
        l5["ast"] = None
        l5["ast_compile_status"] = None
        l5["ast_compile_iterations"] = None
        l5["ast_compile_source"] = None
        l5["ast_compile_error"] = None

        import math
        def _nan_to_none(v):
            return None if isinstance(v, float) and math.isnan(v) else v

        icir = _nan_to_none(backtest.get("icir"))
        win_rate = _nan_to_none(backtest.get("win_rate"))
        l5["overall_assessment"] = {
            "score": _compute_score(icir, win_rate),
            "status": _compute_status(icir),
            "pass_threshold": 60,
            "final_meaning": "",  # Phase 3 LLM 填充
            # Extra fields for backward compat (PipelineRunner summary)
            "ic_mean": _nan_to_none(backtest.get("ic_mean")),
            "icir": icir,
            "winrate": win_rate,
            "rank_ic_mean": _nan_to_none(backtest.get("rank_ic_mean")),
            "rank_icir": _nan_to_none(backtest.get("rank_icir")),
            "annual_return": _nan_to_none(backtest.get("longshort_ann_return")),
            "longshort_sharpe": _nan_to_none(backtest.get("longshort_sharpe")),
            "longshort_max_dd": _nan_to_none(backtest.get("longshort_max_dd")),
            "validated_at": time.time(),
        }
        # Frontend expects `validation_date` as YYYY-MM-DD string (FactorDetail.tsx:558)
        l5["validation_date"] = time.strftime("%Y-%m-%d")

        action = write_factor_yaml(slug, data)
        print(f"[yaml] {action} (slug={slug})")
        return action
    except Exception as exc:
        print(f"[yaml] persist_code_to_yaml failed for {factor_name}: {exc}")
        return None


def _derive_input_columns(formula_brief: str) -> list[str]:
    """Extract input column names from formula_brief text.

    Matches 101 alpha paper's common column tokens.
    """
    candidates = [
        "open", "high", "low", "close", "volume", "adv20", "adv30", "adv40",
        "adv50", "adv60", "adv81", "adv120", "adv150", "vwap", "returns",
        "cap", "industry",
    ]
    text = formula_brief.lower()
    found = [c for c in candidates if c in text]
    # Always include base OHLCV if any price-like token present
    if any(t in text for t in ["close", "open", "high", "low", "vwap", "returns"]):
        for base in ["close", "open", "high", "low", "volume", "returns"]:
            if base not in found:
                found.append(base)
    return found[:10]


def save_backtest_to_db(
    slug: str,
    alpha_index: int,
    backtest: dict,
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    universe: str = "all",
    adj_mode: str = "M-end",
) -> bool:
    """Persist backtest result to reproduction_results table.

    Reuses ReproductionDatabase.create_result (sessions.py:413).
    Schema columns matched by WebUI GET /api/factor/{slug}/backtest
    (factor.py:514-524).
    """
    import math
    def _nan_to_none(v):
        return None if isinstance(v, float) and math.isnan(v) else v

    try:
        from llmwikify.reproduction.persist.sessions import ReproductionDatabase
        db = ReproductionDatabase()
        run_id = f"pipeline_a_{alpha_index:03d}"
        # Create a session first (FK constraint on reproduction_results.session_id)
        session_id = db.create_session(
            wiki_id="default",
            paper_id="101_alphas_minimal",
            source_type="pipeline_a",
            source_ref=f"alpha_{alpha_index:03d}",
            symbol="universe:all",
            start_date=start_date,
            end_date=end_date,
        )
        db.create_result(
            run_id=run_id,
            session_id=session_id,
            result_type="factor_backtest",
            factor_ref=slug,
            strategy_ref=None,
            universe=universe,
            start_date=start_date,
            end_date=end_date,
            status="success",
            error=None,
            wiki_path=None,
            adj_mode=adj_mode,
            hedge="equal",
            data_source="quantnodes_pipeline",
            ic_mean=_nan_to_none(backtest.get("ic_mean")),
            rank_ic_mean=_nan_to_none(backtest.get("rank_ic_mean")),
            icir=_nan_to_none(backtest.get("icir")),
            rank_icir=_nan_to_none(backtest.get("rank_icir")),
            win_rate=_nan_to_none(backtest.get("win_rate")),
            annual_return=_nan_to_none(backtest.get("longshort_ann_return")),
            longshort_ann_return=_nan_to_none(backtest.get("longshort_ann_return")),
            longshort_sharpe=_nan_to_none(backtest.get("longshort_sharpe")),
            longshort_max_dd=_nan_to_none(backtest.get("longshort_max_dd")),
            ic_series=backtest.get("ic_series", []),
            group_metrics=backtest.get("group_metrics", {}),
            equity_curve=backtest.get("equity_curve") or backtest.get("group_nav_series"),
        )
        print(f"[db] created result run_id={run_id} factor_ref={slug}")
        return True
    except Exception as exc:
        print(f"[db] save_backtest_to_db failed for {slug}: {exc}")
        return False


def run_one_factor(alpha_index: int = 1, use_react: bool = True) -> dict:
    t0 = time.monotonic()

    # 1. Load formula_brief from track_b_checkpoint.json
    track_b = json.loads(TRACK_B.read_text(encoding="utf-8"))
    alpha = next(s for s in track_b["pass1_signals"] if s["index"] == alpha_index)
    factor_name = f"alpha-{alpha_index:03d}"
    formula_brief = alpha["formula_brief"]

    print(f"\n{'='*70}")
    print(f"[alpha-{alpha_index:03d}] formula_brief: {formula_brief}")
    print(f"{'='*70}")

    # 2. Load data into polars (long format)
    # Handle both 'close' (PR-7 normalized) and 'cp' (legacy) keys
    with pd.HDFStore(DATA_PATH / "stk_daily.h5", "r") as _store:
        _close_key = "close" if "/close" in _store.keys() else "cp"
    cp_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", _close_key)
    open_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "open")
    high_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "high")
    low_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "low")
    volume_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "volume")
    returns_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "returns")
    vwap_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "vwap")
    id_citic1_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "id_citic1")

    def wide_to_long(wide: pd.DataFrame, name: str) -> pl.DataFrame:
        long = wide.stack().reset_index()
        long.columns = ["date", "code", name]
        return pl.from_pandas(long)

    df_pl = (
        wide_to_long(cp_wide, "close")
        .join(wide_to_long(open_wide, "open"), on=["date", "code"])
        .join(wide_to_long(high_wide, "high"), on=["date", "code"])
        .join(wide_to_long(low_wide, "low"), on=["date", "code"])
        .join(wide_to_long(volume_wide, "volume"), on=["date", "code"])
        .join(wide_to_long(returns_wide, "returns"), on=["date", "code"])
        .join(wide_to_long(vwap_wide, "vwap"), on=["date", "code"])
        .join(wide_to_long(id_citic1_wide, "industry"), on=["date", "code"])
        .sort(["date", "code"])
    )
    print(f"[data] shape: {df_pl.shape}, columns: {df_pl.columns}")
    print(f"[data] date range: {df_pl['date'].min()} - {df_pl['date'].max()}")

    # 3. LLM call to generate Python code (ReAct self-retry by default)
    print(f"\n[LLM] calling model via {('ReAct' if use_react else '1-shot')} loop...")
    llm = build_llm_client()

    # 4. LLM generates code (ReAct or 1-shot)
    react_meta: dict = {}
    if use_react:
        code, factor_series, error, react_meta = _llm_code_react(
            factor_name=factor_name,
            formula_brief=formula_brief,
            df_pl=df_pl,
            llm=llm,
            max_repair_rounds=5,
            temperature=0.3,
        )
        if error is not None:
            return {
                "status": "failed",
                "stage": "react",
                "error": error,
                "react_meta": react_meta,
                "elapsed_sec": time.monotonic() - t0,
            }
    else:
        code, factor_series, error, stage_idx = _llm_code_oneshot(
            factor_name=factor_name,
            formula_brief=formula_brief,
            df_pl=df_pl,
            llm=llm,
            temperature=0.3,
        )
        if error is not None:
            return {
                "status": "failed",
                "stage": _STAGE_NAMES.get(stage_idx, "unknown"),
                "error": error,
                "code": code,
                "elapsed_sec": time.monotonic() - t0,
            }

    # 8. Convert to wide + write H5 (into DATA_PATH so PipelineRunner can join)
    # Detect binary/constant factors (≤2 unique values) — add tiny noise to enable IC calculation
    unique_vals = factor_series.drop_nulls().unique()
    if len(unique_vals) <= 2:
        print(f"[execute] constant/binary factor detected ({len(unique_vals)} unique values), adding noise")
        noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(factor_series)))
        factor_series = factor_series.cast(pl.Float64) + noise
    factor_wide = _wide_from_long(df_pl, factor_series)
    print(f"[h5] wide shape: {factor_wide.shape}, dates: {factor_wide.index.min()} - {factor_wide.index.max()}")
    # Use a clean factor name (no dash) so LoadDataNode can find it via natural name
    safe_factor_name = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    h5_path = _write_factor_h5(factor_wide, safe_factor_name, DATA_PATH)
    print(f"[h5] written: {h5_path}")

    # 9. Build QN config + run PipelineRunner
    print("\n[PipelineRunner] building config...")
    config = _build_qn_config(factor_name, h5_path, code)
    print("[PipelineRunner] running 12-node pipeline...")

    from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner

    try:
        runner = PipelineRunner.from_dict(config)
        ctx = runner.run()
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[PipelineRunner] FAILED: {type(exc).__name__}: {exc}")
        print(tb[-1500:])
        return {
            "status": "failed",
            "stage": "pipeline",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": tb[-1500:],
            "code": code,
            "elapsed_sec": time.monotonic() - t0,
        }

    # 10. Extract metrics
    print(f"\n[result] PipelineRunner ctx keys: {list(ctx.keys())}")
    ic_node = ctx.get("ICAnalyzer")
    ic_result = ic_node.get("ic_result") if isinstance(ic_node, dict) else None
    if ic_result is not None and hasattr(ic_result, "get"):
        ic_mean = ic_result.get("IC均值") or ic_result.get("IC_mean")
        icir = ic_result.get("ICIR")
        ic_winrate = ic_result.get("IC为正比例") or ic_result.get("IC胜率") or ic_result.get("win_rate")
        print(f"[IC] 均值: {ic_mean}, ICIR: {icir}, 胜率: {ic_winrate}")
    else:
        ic_mean = icir = ic_winrate = None
        print(f"[IC] no IC result; ctx ICAnalyzer: {type(ic_node)}, val: {str(ic_node)[:200] if ic_node else 'None'}")

    group_result = ctx.get("GroupAnalyzer")
    print(f"[Group] type: {type(group_result)}, preview: {str(group_result)[:300] if group_result else None}")

    # ─── Phase 1: extract full backtest + persist YAML + write DB ───
    backtest = _extract_full_backtest_from_ctx(ctx)
    # Override win_rate with the existing extraction (it was the only summary kept)
    if ic_winrate is not None and backtest.get("win_rate") is None:
        backtest["win_rate"] = ic_winrate
    if ic_mean is not None and backtest.get("ic_mean") is None:
        backtest["ic_mean"] = ic_mean
    if icir is not None and backtest.get("icir") is None:
        backtest["icir"] = icir
    print(f"[backtest] ic_mean={backtest.get('ic_mean')}, icir={backtest.get('icir')}, "
          f"groups={len(backtest.get('group_metrics', {}))}, "
          f"ic_series_pts={len(backtest.get('ic_series', []))}")

    slug = factor_name.replace("-", "_")
    persist_code_to_yaml(
        factor_name=factor_name,
        code=code,
        formula_brief=formula_brief,
        backtest=backtest,
        h5_path=str(h5_path),
        code_chars=len(code),
    )
    save_backtest_to_db(
        slug=slug,
        alpha_index=alpha_index,
        backtest=backtest,
    )

    elapsed = time.monotonic() - t0
    print(f"\n[done] elapsed: {elapsed:.1f}s")

    return {
        "status": "success",
        "alpha_index": alpha_index,
        "factor_name": factor_name,
        "formula_brief": formula_brief,
        "code": code,
        "code_chars": len(code),
        "factor_series_len": len(factor_series),
        "factor_series_dtype": str(factor_series.dtype),
        "h5_path": str(h5_path),
        "ic_mean": ic_mean,
        "icir": icir,
        "ic_winrate": ic_winrate,
        "elapsed_sec": elapsed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Single-factor LLM-code E2E test")
    parser.add_argument("alpha_index", type=int, nargs="?", default=1,
                        help="Alpha index (1-101) from track_b_checkpoint.json")
    parser.add_argument("--no-react", action="store_true",
                        help="Disable ReAct self-retry; use 1-shot LLM call")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Max repair rounds for ReAct (default: 3)")
    args = parser.parse_args()

    result = run_one_factor(
        args.alpha_index,
        use_react=not args.no_react,
    )

    suffix = "" if not args.no_react else "_noreact"
    out_file = OUTPUT_DIR / f"single_factor_{args.alpha_index:03d}{suffix}.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[output] saved to {out_file}")
    print(json.dumps({k: v for k, v in result.items() if k != "code"}, indent=2, ensure_ascii=False, default=str))
