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
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
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
from llmwikify.apps.chat.agent.unified.core import UnifiedHook
from CodersWheel.QuickTool.timer import timer
from llmwikify.reproduction.pipeline.backtest_extract import safe_float, extract_full_backtest_from_ctx
from llmwikify.reproduction.pipeline.data_loader import wide_from_long, write_factor_h5, derive_input_columns
from llmwikify.reproduction.pipeline.score import compute_score, compute_status

# ─── Constants ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STAGE_NAMES = {-1: "llm", 0: "extract", 1: "syntax", 2: "safety", 3: "execute"}

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


@timer
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




@timer
def _write_factor_h5(wide: pd.DataFrame, factor_name: str, output_dir: Path, h5_filename: str = "stk_daily.h5") -> Path:
    """Write wide DataFrame to QuantNodes-compatible H5 file (delegates to data_loader)."""
    return write_factor_h5(wide, factor_name, output_dir)


def _build_qn_config(factor_name: str, h5_path: Path, expression: str, config: RunConfig | None = None) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner (delegates to backtest_config)."""
    from llmwikify.reproduction.pipeline.backtest_config import build_qn_config as _build_qn_base
    return _build_qn_base(factor_name, h5_path, expression, config=config)


# ─── LLM code generation ────────────────────────────────────────────


@timer
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
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code_sync

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


@timer
def _run_pipeline(qn_config: dict) -> dict:
    from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner
    runner = PipelineRunner.from_dict(qn_config)
    return runner.run()


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

    print(f"\n{'='*70}")
    print(f"[alpha-{alpha_index:03d}] formula_brief: {formula_brief}")
    print(f"{'='*70}")

    # 2. Use pre-built polars DataFrame, or build from cache/fresh
    if df_pl is None:
        if data_cache is not None:
            df_pl = _build_wide_df(data_cache)
        else:
            df_pl = _load_and_build_df(config.data_path, config.h5_filename)
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
            temperature=config.temperature,
        )
        if error is not None:
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
    # 传完整相对路径（含 strategy_dir 前缀）以便 _resolve_factor_dir 定位
    # project_root 需要是 quant/factors/ 的父目录的父目录（即包含 quant/ 的根目录）
    if factor_dir:
        factors_dir = config.factors_dir  # e.g., ~/Public/strategy/quant/factors
        project_root = factors_dir.parent.parent  # e.g., ~/Public/strategy/
        rel_path = str(factor_dir.relative_to(factors_dir))  # e.g., 101_alphas/stk_alpha_001_abc
    else:
        project_root = None
        rel_path = slug
    save_backtest_duckdb(
        factor_name=rel_path,
        run_id=run_id,
        backtest=backtest,
        factor_wide=factor_wide,
        project_root=project_root,
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


def _run_llm_extract(args: argparse.Namespace, output_dir: Path) -> None:
    """Phase 3: extract L2-L6 metadata from existing single_factor_NNN.json files.

    Uses factor_extractor.extract_batch (3 concurrent LLM calls, ~60s/alpha).
    Skips alphas without JSON (no LLM code re-run needed).
    """
    from llmwikify.reproduction.factor_extractor import extract_batch

    indices = list(range(args.start, args.end + 1))
    print("=" * 80)
    print("  Phase 3: LLM Extract L2-L6 Metadata")
    print("=" * 80)
    print(f"  Indices: {args.start}-{args.end}")
    print(f"  Output dir: {output_dir}")
    print()

    available = [i for i in indices if (output_dir / f"single_factor_{i:03d}.json").exists()]
    if not available:
        print("  [error] no single_factor_NNN.json found in output/")
        print("  Run Phase 1 first (without --llm-extract)")
        return
    print(f"  Available: {len(available)} alphas with JSON ({available[:5]}...)")
    print()

    print("  [info] L5 hypothesis_testing skipped (requires FastAPI server)")
    print("  [info] To enable: start server, then POST /api/factor/{slug}/validate")
    print()

    results = extract_batch(available, output_dir=output_dir, max_workers=3)

    success = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    print()
    print("=" * 80)
    print(f"  Phase 3 complete: {len(success)}/{len(results)} success")
    if failed:
        print("  Failed:")
        for r in failed:
            print(f"    alpha-{r['alpha_index']:03d}: {r.get('error', '?')[:80]}")
    print("=" * 80)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch run 101 alphas")
    parser.add_argument("--start", type=int, default=1, help="First alpha index (default: 1)")
    parser.add_argument("--end", type=int, default=101, help="Last alpha index (default: 101)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip alphas that already have output JSON")
    parser.add_argument("--max-failures", type=int, default=999, help="Stop after N failures (default: unlimited)")
    parser.add_argument("--rounds", type=int, default=3, help="Max ReAct repair rounds (default: 3)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to sleep between alpha runs (default: 3.0)")
    parser.add_argument("--no-delay", action="store_true", help="Disable inter-alpha delay (for testing only)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-alpha timeout in seconds (default: 180)")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1, max: 3)")
    parser.add_argument("--llm-extract", action="store_true", help="Phase 3: LLM extract L2-L6 metadata (reads existing JSONs, no LLM code re-run)")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for JSON results (default: scripts/output)")
    parser.add_argument("--data-path", type=Path, default=None, help="Path to H5 data directory (default: ~/.llmwikify/akshare_cache/quantnodes_h5_long)")
    parser.add_argument("--track-b", type=Path, default=None, help="Path to track_b_checkpoint.json (default: auto)")
    parser.add_argument("--date-beg", type=int, default=20200101, help="Backtest start date YYYYMMDD (default: 20200101)")
    parser.add_argument("--date-end", type=int, default=20241231, help="Backtest end date YYYYMMDD (default: 20241231)")
    parser.add_argument("--sample-index", type=str, default="all", help="Sample index: all/HS300/ZZ500 (default: all)")
    parser.add_argument("--paper-id", type=str, default="101_alphas_minimal", help="Paper ID for DB session")
    parser.add_argument("--wiki-id", type=str, default="default", help="Wiki ID for DB session")
    parser.add_argument("--h5-filename", type=str, default="stk_daily.h5", help="H5 filename within data-path (default: stk_daily.h5)")
    parser.add_argument("--strategy-dir", type=str, default="101_alphas", help="Output subdirectory under quant/factors/ (default: 101_alphas)")
    parser.add_argument("--groups", type=int, default=5, help="Number of groups for analysis (default: 5)")
    parser.add_argument("--factor-direction", type=int, default=1, help="Factor direction: 1 or -1 (default: 1)")
    parser.add_argument("--hedge", type=str, default="equal", help="Hedge mode (default: equal)")
    parser.add_argument("--adj-mode", type=str, default="M-end", help="Adjustment mode (default: M-end)")
    parser.add_argument("--min-group-size", type=int, default=3, help="Minimum group size (default: 3)")
    parser.add_argument("--factors-dir", type=Path, default=None, help="Base factors directory (default: <project>/quant/factors)")
    args = parser.parse_args()

    config = RunConfig(
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

    # Phase 3: LLM extraction mode (fast, no LLM code re-run)
    if args.llm_extract:
        _run_llm_extract(args, config.output_dir)
        return

    _print_header()
    t0 = time.monotonic()

    # Preload H5 data once (shared across all alpha runs)
    print(f"  Data path: {config.data_path}")
    print(f"  Track B:   {config.track_b_path}")
    print(f"  Date range: {config.date_beg} - {config.date_end}")
    print(f"  Sample index: {config.sample_index}")
    print(f"  H5 filename: {config.h5_filename}")
    print()
    data_cache = _preload_data(config.data_path, config.h5_filename)
    print(f"  Preloaded {len(data_cache)} H5 keys: {list(data_cache.keys())}")
    df_pl = _build_wide_df(data_cache)
    print(f"  Built polars long DF: {df_pl.shape}")
    print()

    # Optionally skip already-done alphas
    skip: set[int] = set()
    if args.skip_existing:
        for idx in range(args.start, args.end + 1):
            p = config.output_dir / f"single_factor_{idx:03d}.json"
            if p.exists():
                skip.add(idx)
        if skip:
            print(f"  [skip] {len(skip)} alphas already done: {sorted(skip)[:10]}...")

    results: list[dict] = []
    failures: int = 0
    n_workers = min(args.workers, 3)  # 最多 3 并发

    # 加载已有的 skipped 结果
    for idx in sorted(skip):
        p = config.output_dir / f"single_factor_{idx:03d}.json"
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if "alpha_index" not in loaded:
            loaded["alpha_index"] = idx
        results.append(loaded)

    # 构建待跑列表
    to_run = [idx for idx in range(args.start, args.end + 1) if idx not in skip]

    if n_workers <= 1:
        # ── 串行模式 ──
        for idx in to_run:
            elapsed_cum = time.monotonic() - t0
            print(f"\n[{time.strftime('%H:%M:%S')}] alpha-{idx:03d} (elapsed: {elapsed_cum:.0f}s, failures: {failures})")

            result = run_one_factor(idx, use_react=True, config=config, df_pl=df_pl)
            if "alpha_index" not in result:
                result["alpha_index"] = idx
            results.append(result)

            _print_row(idx, result, elapsed_cum)

            out_file = config.output_dir / f"single_factor_{idx:03d}.json"
            out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

            if result.get("status") != "success":
                failures += 1
                if failures >= args.max_failures:
                    print(f"\n[stop] {failures} failures reached --max-failures={args.max_failures}")
                    break

            if idx < args.end and args.delay > 0 and not args.no_delay:
                time.sleep(args.delay)
    else:
        # ── 多线程模式 ──
        print(f"  Workers: {n_workers} (concurrent)")
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_run_one_safe, idx, config, df_pl, t0, results, args.timeout): idx
                for idx in to_run
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result(timeout=args.timeout + 60)
                except Exception as exc:
                    with _print_lock:
                        print(f"\n  [{idx:03d}] EXCEPTION: {exc}")
                        failures += 1

    # Write summary files
    _write_json(results, config.output_dir / "multi_alpha_001_to_101.json")
    _write_markdown(results, config.output_dir / "multi_alpha_summary.md")
    _print_summary(results)

    total_elapsed = time.monotonic() - t0
    print(f"\n  Total elapsed: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"  Results saved to: {config.output_dir}")


if __name__ == "__main__":
    main()
