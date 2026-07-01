"""Run all 101 alphas in batch mode and produce a summary.

Self-contained: includes run_one_factor and all dependencies (previously
in test_one_factor_llm_code.py).

Usage:
  python scripts/run_101_alphas.py                  # run all
  python scripts/run_101_alphas.py --start 1 --end 5  # run 1..5
  python scripts/run_101_alphas.py --skip-existing   # skip already-done files
  python scripts/run_101_alphas.py --max-failures 5  # stop after 5 failures
  python scripts/run_101_alphas.py --output-dir /tmp/alpha_test

Output:
  <output-dir>/multi_alpha_001_to_101.json
  <output-dir>/multi_alpha_summary.md  (human-readable table)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
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
from llmwikify.kernel.agent import UnifiedHook
from llmwikify.foundation.logging import log_timing, setup_logging
from llmwikify.reproduction.pipeline.backtest_extract import safe_float, extract_full_backtest_from_ctx
from llmwikify.reproduction.pipeline.data_loader import wide_from_long, write_factor_h5, derive_input_columns, load_and_build_df
from llmwikify.reproduction.pipeline.stages.codegen import llm_code_oneshot
from llmwikify.reproduction.pipeline.score import compute_score, compute_status

# ─── Constants ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STAGE_NAMES = {-1: "llm", 0: "extract", 1: "syntax", 2: "safety", 3: "execute"}

# ─── Logger ──────────────────────────────────────────────────────────
setup_logging(
    log_dir=PROJECT_ROOT / "scripts" / "output",
    log_file="run_101_alphas.log",
    force=True,
)
logger = logging.getLogger("run_101_alphas")

# ── 并发控制 ──────────────────────────────────────────────
_llm_semaphore = threading.Semaphore(3)  # api.minimaxi.com ≤3 并发
_print_lock = threading.Lock()


@dataclass
class RunConfig:
    """Centralized configuration for batch alpha runs."""

    data_path: Path = field(default_factory=lambda: Path.home() / ".llmwikify" / "akshare_cache" / "quantnodes_h5_long")
    track_b_path: Path = field(default_factory=lambda: PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "scripts" / "output")
    date_beg: int = 20200101
    date_end: int = 20241231
    sample_index: str = "all"
    paper_id: str = "101_alphas_minimal"
    wiki_id: str = "default"
    max_repair_rounds: int = 3
    temperature: float = 0.3
    h5_filename: str = "stk_daily.h5"
    factors_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "quant" / "factors")

    # ── 业务配置（参数化）──
    strategy_dir: str = "101_alphas"          # 输出子目录
    asset_type: str = "stock"                 # 资产类型
    category: str = "formulaic"               # 因子分类
    frequency: str = "日频"                    # 频率
    nan_meaning: str = "上市不足或窗口期数据不足"  # NaN 含义
    business_constraints: str = "支持日频调仓, T+1 信号"
    pass_threshold: int = 60                  # 通过阈值
    hedge: str = "equal"                      # 对冲方式
    adj_mode: str = "M-end"                   # 复权模式
    groups: int = 5                           # 分组数
    factor_direction: int = 1                 # 因子方向
    output_format: list[str] = field(default_factory=lambda: ["parquet", "json"])
    min_group_size: int = 3                   # 最小组大小

    # ── Stage 1: Paper extraction ──
    paper_path: Path | None = None            # PDF 路径（触发 Stage 1）
    paper_output_root: Path | None = None     # paper 输出根目录（默认 quant/papers/）
    run_pass2: bool = True                    # 是否跑 Track B Pass 2

    # ── Stage 2: Factor processing ──
    alpha_start: int = 1                      # 起始 alpha index
    alpha_end: int = 101                      # 结束 alpha index
    skip_existing: bool = False               # 跳过已有 JSON 的 alpha
    max_failures: int = 999                   # 最大失败数
    delay: float = 3.0                        # alpha 间延迟（秒）
    no_delay: bool = False                    # 禁用延迟
    timeout: int = 180                        # 单 alpha 超时（秒）
    workers: int = 1                          # 并发数（max 3）

    # ── Stage 2b: LLM extraction ──
    llm_extract: bool = False                 # 是否跑 LLM 元数据提取

    # ── Logging ──
    log_file: Path | None = None              # 日志文件路径（默认 scripts/output/run_101_alphas.log）

    @property
    def report_dir(self) -> Path:
        return self.output_dir / "report"

    @property
    def date_beg_iso(self) -> str:
        s = str(self.date_beg)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    @property
    def date_end_iso(self) -> str:
        s = str(self.date_end)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


# ─── Data loading ────────────────────────────────────────────────────


def _preload_data(data_path: Path, h5_filename: str = "stk_daily.h5") -> dict[str, pd.DataFrame]:
    """Load all H5 keys once → dict of wide DataFrames (date × code).

    Keys: close, open, high, low, volume, returns, vwap, industry.
    """
    h5 = data_path / h5_filename
    with pd.HDFStore(h5, "r") as store:
        close_key = "close" if "/close" in store.keys() else "cp"
    keys = {
        "close": close_key, "open": "open", "high": "high", "low": "low",
        "volume": "volume", "returns": "returns", "vwap": "vwap",
        "industry": "id_citic1",
    }
    return {name: pd.read_hdf(h5, h5_key) for name, h5_key in keys.items()}


@log_timing(logger=logger)
def _build_wide_df(data_cache: dict[str, pd.DataFrame]) -> pl.DataFrame:
    """Convert cached wide DataFrames → single polars long DataFrame (date, code, ...)."""
    def wide_to_long(wide: pd.DataFrame, name: str) -> pl.DataFrame:
        long = wide.stack().reset_index()
        long.columns = ["date", "code", name]
        return pl.from_pandas(long)

    result = wide_to_long(data_cache["close"], "close")
    for col in ("open", "high", "low", "volume", "returns", "vwap", "industry"):
        result = result.join(wide_to_long(data_cache[col], col), on=["date", "code"])
    return result.sort(["date", "code"])



# ─── Utility functions ──────────────────────────────────────────────




@log_timing(logger=logger)
def _write_factor_h5(wide: pd.DataFrame, factor_name: str, output_dir: Path, h5_filename: str = "stk_daily.h5") -> Path:
    """Write wide DataFrame to QuantNodes-compatible H5 file (delegates to data_loader)."""
    return write_factor_h5(wide, factor_name, output_dir)


def _build_qn_config(factor_name: str, h5_path: Path, expression: str, config: RunConfig | None = None) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner (delegates to backtest_config)."""
    from llmwikify.reproduction.pipeline.backtest_config import build_qn_config as _build_qn_base
    return _build_qn_base(factor_name, h5_path, expression, config=config)


# ─── LLM code generation ────────────────────────────────────────────


@log_timing(logger=logger)
def _llm_code_react(
    factor_name: str,
    formula_brief: str,
    df_pl: pl.DataFrame,
    llm: Any,
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
) -> tuple[str | None, pl.Series | None, str | None, dict]:
    """ReAct self-retry path: unified agent loop.

    Returns (code, factor_series, error, react_result_dict).
    """
    from llmwikify.kernel.agent import generate_factor_code_sync

    class _ProgressHook(UnifiedHook):
        """Print progress like the old progress_callback."""
        def on_reason_start(self, ctx):
            print(f"  [REASON] iteration {ctx.iteration}...")

        def on_act_end(self, ctx, result):
            if hasattr(result, "success") and result.success:
                print(f"  [ACT] OK ({getattr(result, 'error_kind', 'none')})")
            else:
                ek = getattr(result, "error_kind", "unknown")
                em = getattr(result, "error", "")[:120]
                print(f"  [ACT] {ek}: {em}")

    result = generate_factor_code_sync(
        factor_name=factor_name,
        formula_brief=formula_brief,
        df=df_pl,
        llm_client=llm,
        max_repair_rounds=max_repair_rounds,
        temperature=temperature,
        hook=_ProgressHook(),
    )

    print(f"\n[Unified] iterations={result.iterations}, "
          f"stop_reason={result.stop_reason}, error={result.error}")

    if result.error:
        return None, None, result.error, result.to_dict()

    return result.code, result.factor_series, None, result.to_dict()


# ─── Backtest extraction ─────────────────────────────────────────────



# ─── Persist functions ───────────────────────────────────────────────




def _make_factor_dir_name(alpha_index: int, code: str) -> str:
    """Generate directory name: stk_alpha_{index:03d}_{md5(code)[:6]}."""
    code_hash = hashlib.md5(code.encode()).hexdigest()[:6]
    return f"stk_alpha_{alpha_index:03d}_{code_hash}"


def persist_code_to_yaml(
    factor_name: str,
    code: str,
    formula_brief: str,
    backtest: dict,
    h5_path: str,
    code_chars: int,
    alpha_index: int = 0,
    config: RunConfig | None = None,
) -> tuple[str | None, Path | None]:
    """Persist code-path factor YAML (delegates to pipeline.persist)."""
    from llmwikify.reproduction.pipeline.persist import persist_code_to_yaml as _persist
    config = config or RunConfig()
    return _persist(
        factor_name, code, formula_brief, backtest, h5_path, code_chars,
        config=config,
        alpha_index=alpha_index,
    )


# ─── run_one_factor ──────────────────────────────────────────────────


@log_timing(logger=logger)
def _run_pipeline(qn_config: dict) -> dict:
    from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner
    runner = PipelineRunner.from_dict(qn_config)
    return runner.run()


@log_timing(logger=logger, label='alpha')
def run_one_factor(
    alpha_index: int = 1,
    use_react: bool = True,
    config: RunConfig | None = None,
    data_cache: dict[str, pd.DataFrame] | None = None,
    df_pl: pl.DataFrame | None = None,
) -> dict:
    t0 = time.monotonic()
    config = config or RunConfig()

    # 1. Load formula_brief from track_b_checkpoint.json
    track_b = json.loads(config.track_b_path.read_text(encoding="utf-8"))
    alpha = next(s for s in track_b["pass1_signals"] if s["index"] == alpha_index)
    factor_name = f"alpha-{alpha_index:03d}"
    formula_brief = alpha["formula_brief"]

    logger.info("[alpha-%03d] formula_brief: %s", alpha_index, formula_brief[:100])
    print(f"\n{'='*70}")
    print(f"[alpha-{alpha_index:03d}] formula_brief: {formula_brief}")
    print(f"{'='*70}")

    # 2. Use pre-built polars DataFrame, or build from cache/fresh
    if df_pl is None:
        if data_cache is not None:
            df_pl = _build_wide_df(data_cache)
        else:
            df_pl = load_and_build_df(config.data_path, config.h5_filename)
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
            max_repair_rounds=config.max_repair_rounds,
            temperature=config.temperature,
        )
        if error is not None:
            logger.warning("[alpha-%03d] failed at react: %s", alpha_index, error[:100])
            return {
                "status": "failed",
                "stage": "react",
                "error": error,
                "react_meta": react_meta,
                "elapsed_sec": time.monotonic() - t0,
            }
    else:
        code, factor_series, error, stage_idx = llm_code_oneshot(
            factor_name=factor_name,
            formula_brief=formula_brief,
            df_pl=df_pl,
            llm=llm,
            temperature=config.temperature,
        )
        if error is not None:
            logger.warning("[alpha-%03d] failed at %s: %s", alpha_index, _STAGE_NAMES.get(stage_idx, "unknown"), error[:100])
            return {
                "status": "failed",
                "stage": _STAGE_NAMES.get(stage_idx, "unknown"),
                "error": error,
                "code": code,
                "elapsed_sec": time.monotonic() - t0,
            }

    # 5. Convert to wide + write H5
    unique_vals = factor_series.drop_nulls().unique()
    if len(unique_vals) <= 2:
        print(f"[execute] constant/binary factor detected ({len(unique_vals)} unique values), adding noise")
        noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(factor_series)))
        factor_series = factor_series.cast(pl.Float64) + noise
    factor_wide = wide_from_long(df_pl, factor_series)
    print(f"[h5] wide shape: {factor_wide.shape}, dates: {factor_wide.index.min()} - {factor_wide.index.max()}")
    safe_factor_name = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    h5_path = _write_factor_h5(factor_wide, safe_factor_name, config.data_path, config.h5_filename)
    print(f"[h5] written: {h5_path}")

    # 6. Build QN config + run PipelineRunner
    print("\n[PipelineRunner] building config...")
    qn_config = _build_qn_config(factor_name, h5_path, code, config=config)
    print("[PipelineRunner] running 12-node pipeline...")

    try:
        ctx = _run_pipeline(qn_config)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.warning("[alpha-%03d] failed at pipeline: %s: %s", alpha_index, type(exc).__name__, str(exc)[:100])
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

    # 7. Extract metrics (single source of truth via backtest_extract)
    backtest = extract_full_backtest_from_ctx(ctx)
    logger.info("[alpha-%03d] backtest IC=%.4f, ICIR=%.4f, WinRate=%.1f%%",
                alpha_index, backtest.get("ic_mean", 0), backtest.get("icir", 0),
                (backtest.get("win_rate", 0) or 0) * 100)
    print(f"[backtest] ic_mean={backtest.get('ic_mean')}, icir={backtest.get('icir')}, "
          f"groups={len(backtest.get('group_metrics', {}))}, "
          f"ic_series_pts={len(backtest.get('ic_series', []))}")

    slug = factor_name.replace("-", "_")
    _, factor_dir = persist_code_to_yaml(
        factor_name=factor_name,
        code=code,
        formula_brief=formula_brief,
        backtest=backtest,
        h5_path=str(h5_path),
        code_chars=len(code),
        alpha_index=alpha_index,
        config=config,
    )

    # Save backtest + factor_values to per-factor DuckDB
    from llmwikify.reproduction.persist.factor_library import save_backtest_duckdb
    run_id = f"pipeline_a_{alpha_index:03d}"
    if factor_dir:
        rel_path = str(factor_dir.relative_to(config.factors_dir))
    else:
        rel_path = slug
    save_backtest_duckdb(
        factor_name=rel_path,
        run_id=run_id,
        backtest=backtest,
        factor_wide=factor_wide,
        factors_dir=config.factors_dir,
    )

    elapsed = time.monotonic() - t0
    logger.info("[alpha-%03d] success (%.1fs)", alpha_index, elapsed)
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
        "ic_mean": backtest.get("ic_mean"),
        "icir": backtest.get("icir"),
        "ic_winrate": backtest.get("win_rate"),
        "elapsed_sec": elapsed,
    }


# ─── Batch runner ────────────────────────────────────────────────────


def _print_header() -> None:
    print("=" * 100)
    print("  101-Alpha Batch Runner")
    print("=" * 100)


def _print_row(idx: int, result: dict, elapsed_cum: float) -> None:
    status = result.get("status", "unknown")
    ic = result.get("ic_mean")
    icir = result.get("icir")
    wr = result.get("ic_winrate")
    elapsed = result.get("elapsed_sec", 0)

    ic_str = f"{ic:+.4f}" if isinstance(ic, (int, float)) and ic == ic else "  NaN"
    icir_str = f"{icir:+.4f}" if isinstance(icir, (int, float)) and icir == icir else "  NaN"
    wr_str = f"{wr * 100:5.1f}%" if isinstance(wr, (int, float)) and wr == wr else "  NaN"
    note = result.get("stage", "") if status != "success" else ""

    print(f"  {idx:>3}  {status:<8} {ic_str:>10} {icir_str:>10} {wr_str:>8}  {elapsed:>6.1f}s  {note}")


def _print_summary(results: list[dict]) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]

    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    avg_ic = sum(ic_means) / len(ic_means) if ic_means else None
    avg_icir = sum(icirs) / len(icirs) if icirs else None
    avg_wr = sum(winrates) / len(winrates) if winrates else None

    print("\n" + "=" * 100)
    print("  Summary")
    print("=" * 100)
    print(f"  Total:  {len(results)}  |  Success: {len(success)}  |  Failed: {len(failed)}")
    if ic_means:
        print(f"  Avg IC: {avg_ic:+.4f}  |  Avg ICIR: {avg_icir:+.4f}  |  Avg Winrate: {(avg_wr or 0) * 100:.1f}%")
    if failed:
        print("\n  Failed alphas:")
        for r in failed:
            idx = r.get("alpha_index")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            print(f"    alpha-{idx_s}: {r.get('stage', '?')} - {r.get('error', '?')[:80]}")
    print("=" * 100)


def _write_json(results: list[dict], path: Path) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    summary = {
        "total": len(results),
        "success_count": len(success),
        "failed_count": len(failed),
        "aggregate": {
            "ic_mean_avg": round(sum(ic_means) / len(ic_means), 4) if ic_means else None,
            "icir_avg": round(sum(icirs) / len(icirs), 4) if icirs else None,
            "winrate_avg": round(sum(winrates) / len(winrates), 4) if winrates else None,
        },
        "alphas": [
            {
                "index": r.get("alpha_index"),
                "status": r.get("status"),
                "ic_mean": r.get("ic_mean"),
                "icir": r.get("icir"),
                "ic_winrate": r.get("ic_winrate"),
                "code_chars": r.get("code_chars"),
                "elapsed_sec": r.get("elapsed_sec"),
                "stage": r.get("stage", ""),
                "error": r.get("error", "")[:200],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _write_markdown(results: list[dict], path: Path) -> None:
    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    ic_means = [r["ic_mean"] for r in success if r.get("ic_mean") is not None and r["ic_mean"] == r["ic_mean"]]
    icirs = [r["icir"] for r in success if r.get("icir") is not None and r["icir"] == r["icir"]]
    winrates = [r["ic_winrate"] for r in success if r.get("ic_winrate") is not None and r["ic_winrate"] == r["ic_winrate"]]

    lines = [
        "# 101-Alpha Batch Results",
        "",
        f"- Total: {len(results)} | Success: {len(success)} | Failed: {len(failed)}",
    ]
    if ic_means:
        avg_ic = sum(ic_means) / len(ic_means)
        avg_icir = sum(icirs) / len(icirs)
        avg_wr = sum(winrates) / len(winrates)
        lines.append(f"- Avg IC: {avg_ic:+.4f} | Avg ICIR: {avg_icir:+.4f} | Avg Winrate: {avg_wr * 100:.1f}%")
    lines += [
        "",
        "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |",
        "|-------|--------|----|------|---------|------|---------|",
    ]
    for r in results:
        idx = r.get("alpha_index")
        st = r.get("status", "?")
        ic = r.get("ic_mean")
        icir = r.get("icir")
        wr = r.get("ic_winrate")
        ic_s = f"{ic:+.4f}" if isinstance(ic, float) and ic == ic else "NaN"
        icir_s = f"{icir:+.4f}" if isinstance(icir, float) and icir == icir else "NaN"
        wr_s = f"{wr * 100:.1f}%" if isinstance(wr, float) and wr == wr else "NaN"
        cc = r.get("code_chars", 0) or 0
        el = r.get("elapsed_sec", 0) or 0
        idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
        lines.append(f"| alpha-{idx_s} | {st} | {ic_s} | {icir_s} | {wr_s} | {cc} | {el:.1f}s |")

    if failed:
        lines += ["", "## Failed Alphas", ""]
        for r in failed:
            idx = r.get("alpha_index")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            lines.append(f"- alpha-{idx_s}: `{r.get('stage', '?')}` - {r.get('error', '?')[:100]}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@log_timing(logger=logger, label='paper')
def _run_paper_extract(config: RunConfig) -> Path:
    """Stage 1: Run paper extraction and return track_b_checkpoint.json path."""
    from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper

    if not config.paper_path or not config.paper_path.exists():
        raise FileNotFoundError(f"Paper not found: {config.paper_path}")

    output_root = config.paper_output_root or PROJECT_ROOT / "quant" / "papers"

    logger.info("[paper] Starting paper extraction")
    logger.info("[paper] Paper: %s", config.paper_path)
    logger.info("[paper] Paper ID: %s", config.paper_id)
    logger.info("[paper] Output root: %s", output_root)
    logger.info("[paper] Pass 2: %s", config.run_pass2)

    summary = run_one_paper(
        paper_id=config.paper_id,
        source_path=config.paper_path,
        output_root=output_root,
        run_pass2=config.run_pass2,
    )

    if not summary["success"]:
        logger.warning("[paper] Failed: %s", summary.get("error"))
        raise RuntimeError(f"Paper extraction failed: {summary.get('error')}")

    track_b_path = output_root / config.paper_id / "track_b_checkpoint.json"
    if not track_b_path.exists():
        logger.warning("[paper] track_b_checkpoint.json not found after extraction")
        raise FileNotFoundError("track_b_checkpoint.json not found after extraction")

    logger.info("[paper] Success: %d signals extracted", summary["n_signals"])
    logger.info("[paper] Output: %s", track_b_path)

    return track_b_path


@log_timing(logger=logger, label='meta')
def _run_llm_extract(config: RunConfig) -> None:
    """Stage 2b: Extract L2-L6 metadata from existing single_factor_NNN.json files."""
    from llmwikify.reproduction.factor_extractor import extract_batch

    indices = list(range(config.alpha_start, config.alpha_end + 1))
    logger.info("[meta] Starting LLM extraction: alpha %d-%d", config.alpha_start, config.alpha_end)
    logger.info("[meta] Output dir: %s", config.output_dir)

    available = [i for i in indices if (config.output_dir / f"single_factor_{i:03d}.json").exists()]
    if not available:
        logger.warning("[meta] No single_factor_NNN.json found in output/")
        logger.warning("[meta] Run Stage 2 first (without --llm-extract)")
        return
    logger.info("[meta] Available: %d alphas with JSON (%s...)", len(available), available[:5])

    logger.info("[meta] L5 hypothesis_testing skipped (requires FastAPI server)")

    results = extract_batch(available, output_dir=config.output_dir, max_workers=3)

    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    logger.info("[meta] Complete: %d/%d success", len(success), len(results))
    if failed:
        for r in failed:
            logger.warning("[meta] Failed: alpha-%03d: %s", r["alpha_index"], r.get("error", "?")[:80])


def _run_one_safe(
    idx: int,
    config: RunConfig,
    df_pl: pl.DataFrame,
    t0: float,
    results_list: list,
    timeout_sec: int = 180,
) -> dict:
    """带信号量保护 + 超时的单 alpha 执行（线程安全）。"""
    with _llm_semaphore:
        import concurrent.futures
        # 用 ThreadPoolExecutor 内部的超时机制替代 SIGALRM
        result = run_one_factor(idx, use_react=True, config=config, df_pl=df_pl)
        if "alpha_index" not in result:
            result["alpha_index"] = idx

        with _print_lock:
            elapsed_cum = time.monotonic() - t0
            _print_row(idx, result, elapsed_cum)
            out_file = config.output_dir / f"single_factor_{idx:03d}.json"
            out_file.write_text(
                json.dumps(result, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            results_list.append(result)

        return result


@log_timing(logger=logger, label='factor')
def _run_batch_processing(config: RunConfig) -> None:
    """Stage 2: Run batch alpha processing."""
    logger.info("[factor] Starting batch processing: alpha %d-%d", config.alpha_start, config.alpha_end)

    _print_header()
    t0 = time.monotonic()

    logger.info("[factor] Data path: %s", config.data_path)
    logger.info("[factor] Track B: %s", config.track_b_path)
    logger.info("[factor] Date range: %d - %d", config.date_beg, config.date_end)
    logger.info("[factor] Sample index: %s", config.sample_index)
    logger.info("[factor] H5 filename: %s", config.h5_filename)
    logger.info("[factor] Workers: %d", config.workers)

    data_cache = _preload_data(config.data_path, config.h5_filename)
    logger.info("[factor] Preloaded %d H5 keys: %s", len(data_cache), list(data_cache.keys()))

    df_pl = _build_wide_df(data_cache)
    logger.info("[factor] Built polars long DF: %s", df_pl.shape)

    # Skip existing
    skip: set[int] = set()
    if config.skip_existing:
        for idx in range(config.alpha_start, config.alpha_end + 1):
            p = config.output_dir / f"single_factor_{idx:03d}.json"
            if p.exists():
                skip.add(idx)
        if skip:
            logger.info("[factor] Skipping %d alphas: %s...", len(skip), sorted(skip)[:10])

    results: list[dict] = []
    failures: int = 0

    # Load skipped results
    for idx in sorted(skip):
        p = config.output_dir / f"single_factor_{idx:03d}.json"
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if "alpha_index" not in loaded:
            loaded["alpha_index"] = idx
        results.append(loaded)

    to_run = [idx for idx in range(config.alpha_start, config.alpha_end + 1) if idx not in skip]
    logger.info("[factor] To run: %d alphas", len(to_run))

    if config.workers <= 1:
        # Serial mode
        for idx in to_run:
            elapsed_cum = time.monotonic() - t0
            logger.info("[factor] alpha-%03d: starting (elapsed: %.0fs, failures: %d)", idx, elapsed_cum, failures)

            result = run_one_factor(idx, use_react=True, config=config, df_pl=df_pl)
            if "alpha_index" not in result:
                result["alpha_index"] = idx
            results.append(result)

            _print_row(idx, result, elapsed_cum)

            out_file = config.output_dir / f"single_factor_{idx:03d}.json"
            out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

            if result.get("status") != "success":
                failures += 1
                logger.warning("[factor] alpha-%03d: failed (%s)", idx, result.get("error", "?")[:80])
                if failures >= config.max_failures:
                    logger.warning("[factor] Reached max failures (%d), stopping", config.max_failures)
                    break
            else:
                logger.info("[factor] alpha-%03d: success (%.1fs)", idx, result.get("elapsed_sec", 0))

            if idx < config.alpha_end and config.delay > 0 and not config.no_delay:
                time.sleep(config.delay)
    else:
        # Multi-threaded mode
        logger.info("[factor] Using %d concurrent workers", config.workers)
        with ThreadPoolExecutor(max_workers=config.workers) as pool:
            futures = {
                pool.submit(_run_one_safe, idx, config, df_pl, t0, results, config.timeout): idx
                for idx in to_run
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result(timeout=config.timeout + 60)
                except Exception as exc:
                    logger.warning("[factor] alpha-%03d: EXCEPTION: %s", idx, exc)
                    failures += 1

    # Write summary files
    _write_json(results, config.output_dir / "multi_alpha_001_to_101.json")
    _write_markdown(results, config.output_dir / "multi_alpha_summary.md")
    _print_summary(results)

    total_elapsed = time.monotonic() - t0
    logger.info("[factor] Total elapsed: %.1fs (%.1f min)", total_elapsed, total_elapsed / 60)
    logger.info("[factor] Results saved to: %s", config.output_dir)


def main() -> None:
    global logger

    parser = argparse.ArgumentParser(description="Batch run 101 alphas")

    # Stage 1: Paper extraction
    parser.add_argument("--paper-path", type=Path, default=None, help="Path to paper PDF (triggers Stage 1)")
    parser.add_argument("--paper-output-root", type=Path, default=None, help="Output root for paper extraction (default: quant/papers/)")
    parser.add_argument("--no-pass2", action="store_true", help="Skip Track B Pass 2 (only extract formulas)")

    # Stage 2: Factor processing
    parser.add_argument("--start", type=int, default=1, help="First alpha index (default: 1)")
    parser.add_argument("--end", type=int, default=101, help="Last alpha index (default: 101)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip alphas that already have output JSON")
    parser.add_argument("--max-failures", type=int, default=999, help="Stop after N failures (default: unlimited)")
    parser.add_argument("--rounds", type=int, default=3, help="Max ReAct repair rounds (default: 3)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to sleep between alpha runs (default: 3.0)")
    parser.add_argument("--no-delay", action="store_true", help="Disable inter-alpha delay (for testing only)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-alpha timeout in seconds (default: 180)")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1, max: 3)")

    # Stage 2b: LLM metadata extraction
    parser.add_argument("--llm-extract", action="store_true", help="Stage 2b: LLM extract L2-L6 metadata")

    # Logging
    parser.add_argument("--log-file", type=Path, default=None, help="Log file path (default: scripts/output/run_101_alphas.log)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    # Common
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for JSON results (default: scripts/output)")
    parser.add_argument("--data-path", type=Path, default=None, help="Path to H5 data directory")
    parser.add_argument("--track-b", type=Path, default=None, help="Path to track_b_checkpoint.json (default: auto)")
    parser.add_argument("--date-beg", type=int, default=20200101, help="Backtest start date YYYYMMDD (default: 20200101)")
    parser.add_argument("--date-end", type=int, default=20241231, help="Backtest end date YYYYMMDD (default: 20241231)")
    parser.add_argument("--sample-index", type=str, default="all", help="Sample index: all/HS300/ZZ500 (default: all)")
    parser.add_argument("--paper-id", type=str, default="101_alphas_minimal", help="Paper ID")
    parser.add_argument("--wiki-id", type=str, default="default", help="Wiki ID")
    parser.add_argument("--h5-filename", type=str, default="stk_daily.h5", help="H5 filename (default: stk_daily.h5)")
    parser.add_argument("--strategy-dir", type=str, default="101_alphas", help="Output subdirectory (default: 101_alphas)")
    parser.add_argument("--groups", type=int, default=5, help="Number of groups (default: 5)")
    parser.add_argument("--factor-direction", type=int, default=1, help="Factor direction: 1 or -1 (default: 1)")
    parser.add_argument("--hedge", type=str, default="equal", help="Hedge mode (default: equal)")
    parser.add_argument("--adj-mode", type=str, default="M-end", help="Adjustment mode (default: M-end)")
    parser.add_argument("--min-group-size", type=int, default=3, help="Minimum group size (default: 3)")
    parser.add_argument("--factors-dir", type=Path, default=None, help="Base factors directory")
    args = parser.parse_args()

    # Re-initialize logger with user-specified log file
    log_path = Path(args.log_file) if args.log_file else PROJECT_ROOT / "scripts" / "output" / "run_101_alphas.log"
    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO,
        log_dir=log_path.parent,
        log_file=log_path.name,
        force=True,
    )
    logger = logging.getLogger("run_101_alphas")

    config = RunConfig(
        # Paper extraction
        paper_path=args.paper_path,
        paper_output_root=args.paper_output_root,
        run_pass2=not args.no_pass2,

        # Batch processing
        alpha_start=args.start,
        alpha_end=args.end,
        skip_existing=args.skip_existing,
        max_failures=args.max_failures,
        delay=args.delay,
        no_delay=args.no_delay,
        timeout=args.timeout,
        workers=min(args.workers, 3),

        # LLM extraction
        llm_extract=args.llm_extract,

        # Logging
        log_file=log_path,

        # Common
        data_path=args.data_path or Path.home() / ".llmwikify" / "akshare_cache" / "quantnodes_h5_long",
        track_b_path=args.track_b or PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json",
        output_dir=args.output_dir or PROJECT_ROOT / "scripts" / "output",
        date_beg=args.date_beg,
        date_end=args.date_end,
        sample_index=args.sample_index,
        paper_id=args.paper_id,
        wiki_id=args.wiki_id,
        max_repair_rounds=args.rounds,
        h5_filename=args.h5_filename,
        strategy_dir=args.strategy_dir,
        groups=args.groups,
        factor_direction=args.factor_direction,
        hedge=args.hedge,
        adj_mode=args.adj_mode,
        min_group_size=args.min_group_size,
        factors_dir=args.factors_dir or PROJECT_ROOT / "quant" / "factors",
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("RunConfig: %s", config)

    # ── Stage 1: Paper extraction (optional) ──
    track_b_path = args.track_b
    if config.paper_path:
        track_b_path = _run_paper_extract(config)

    # Update config with resolved track_b_path
    if track_b_path:
        config = replace(config, track_b_path=track_b_path)

    # ── Stage 2: Factor processing ──
    if not config.llm_extract:
        _run_batch_processing(config)

    # ── Stage 2b: LLM metadata extraction ──
    if config.llm_extract:
        _run_llm_extract(config)


if __name__ == "__main__":
    main()
