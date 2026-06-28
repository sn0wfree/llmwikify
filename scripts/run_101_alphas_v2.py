"""Run all 101 alphas in batch mode — v2 (class-based refactor).

v2 重构要点:
  - 按阶段划分: PaperStage / FactorStage / MetaStage
  - 有状态功能用类（BaseStage 抽象基类 + 三个子类）
  - 无状态功能用顶层函数（data + reporting）
  - run_one_factor 变为 FactorRunner 类方法，被 FactorStage 复用
  - 输出统一: logger.info() (无 print)
  - 类型注解 + __all__ + __slots__

Usage:
  python scripts/run_101_alphas_v2.py                  # run all
  python scripts/run_101_alphas_v2.py --start 1 --end 5
  python scripts/run_101_alphas_v2.py --skip-existing
  python scripts/run_101_alphas_v2.py --max-failures 5

Output:
  <output-dir>/multi_alpha_001_to_101.json
  <output-dir>/multi_alpha_summary.md  (human-readable table)

设计文档: docs/designs/run_101_alphas_v2_design.md
"""
from __future__ import annotations

__all__ = [
    # Config
    "RunConfig",
    # Base classes
    "BaseStage",
    # Concrete stages
    "PaperStage",
    "MetaStage",
    "FactorRunner",
    "FactorStage",
    # Reporting (P1: split into 3 single-responsibility classes)
    "BatchAggregator",
    "BatchReporter",
    "BatchSerializer",
    # Stateless utilities
    "preload_market_data",
    "build_long_dataframe",
    "load_formula_brief",
]

import argparse
import hashlib
import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
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
from llmwikify.apps.chat.agent.unified.core import UnifiedHook
from llmwikify.foundation.logging import log_timing, setup_logging
from llmwikify.reproduction.pipeline.backtest_extract import safe_float, extract_full_backtest_from_ctx
from llmwikify.reproduction.pipeline.data_loader import wide_from_long, write_factor_h5, derive_input_columns, load_and_build_df
from llmwikify.reproduction.pipeline.stages.codegen import llm_code_oneshot
from llmwikify.reproduction.pipeline.score import compute_score, compute_status

# ─── Constants ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STAGE_NAMES: dict[int, str] = {-1: "llm", 0: "extract", 1: "syntax", 2: "safety", 3: "execute"}

# ─── Logger ──────────────────────────────────────────────────────────
setup_logging(
    log_dir=PROJECT_ROOT / "scripts" / "output",
    log_file="run_101_alphas_v2.log",
    force=True,
)
logger = logging.getLogger("run_101_alphas_v2")

# ── 并发控制 ──────────────────────────────────────────────
_llm_semaphore = threading.Semaphore(3)  # api.minimaxi.com ≤3 并发
_print_lock = threading.Lock()


@dataclass(slots=True)
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


def preload_market_data(data_path: Path, h5_filename: str = "stk_daily.h5") -> dict[str, pd.DataFrame]:
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
def build_long_dataframe(data_cache: dict[str, pd.DataFrame]) -> pl.DataFrame:
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



def _make_factor_dir_name(alpha_index: int, code: str) -> str:
    """Generate directory name: stk_alpha_{index:03d}_{md5(code)[:6]}.

    Dead code per user request: not deleted, kept as utility.
    The same logic is also inlined in src/llmwikify/reproduction/pipeline/persist.py.
    """
    code_hash = hashlib.md5(code.encode()).hexdigest()[:6]
    return f"stk_alpha_{alpha_index:03d}_{code_hash}"


# ─── Batch runner ────────────────────────────────────────────────────


class BatchAggregator:
    """Pure computation: NaN-safe metrics over batch results.

    Bug 7 副作用解决：aggregate + format_metric 共享同一 `import math`（拆类后只需 1 次）。
    """

    __slots__ = ()

    @staticmethod
    def aggregate(results: list[dict]) -> dict[str, Any]:
        """Compute aggregate metrics over successful results (NaN-filtered).

        Returns dict with keys: total, success_count, failed_count,
        ic_mean, icir, winrate.
        """
        import math

        success = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]

        def _finite(xs: list[float]) -> list[float]:
            return [x for x in xs if isinstance(x, (int, float)) and not math.isnan(x)]

        ic_means = _finite([r.get("ic_mean", 0) for r in success])
        icirs = _finite([r.get("icir", 0) for r in success])
        winrates = _finite([r.get("ic_winrate", 0) for r in success])

        return {
            "total": len(results),
            "success_count": len(success),
            "failed_count": len(failed),
            "ic_mean": round(sum(ic_means) / len(ic_means), 4) if ic_means else None,
            "icir": round(sum(icirs) / len(icirs), 4) if icirs else None,
            "winrate": round(sum(winrates) / len(winrates), 4) if winrates else None,
        }

    @staticmethod
    def format_metric(value: float | None, fmt: str = "+.4f", na: str = "  NaN") -> str:
        """Format a single metric with NaN-safe fallback."""
        import math
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return na
        return f"{value:{fmt}}"


class BatchReporter:
    """Logger output: banner / row / summary."""

    __slots__ = ()

    @staticmethod
    def log_banner() -> None:
        """Log batch runner header."""
        logger.info("=" * 100)
        logger.info("  101-Alpha Batch Runner (v2)")
        logger.info("=" * 100)

    @staticmethod
    def log_row(idx: int, result: dict, elapsed_cum: float) -> None:
        """Log one alpha row result."""
        status: str = result.get("status", "unknown")
        elapsed: float = result.get("elapsed_sec", 0)
        note: str = result.get("stage", "") if status != "success" else ""

        ic_str = BatchAggregator.format_metric(result.get("ic_mean"))
        icir_str = BatchAggregator.format_metric(result.get("icir"))
        wr = result.get("ic_winrate")
        wr_str = f"{wr * 100:5.1f}%" if isinstance(wr, (int, float)) else "  NaN"

        logger.info("  %3d  %-8s %10s %10s %8s  %6.1fs  %s",
                    idx, status, ic_str, icir_str, wr_str, elapsed, note)

    @staticmethod
    def log_summary(results: list[dict]) -> None:
        """Log batch summary."""
        agg = BatchAggregator.aggregate(results)
        success = agg["success_count"]
        failed = agg["failed_count"]

        logger.info("=" * 100)
        logger.info("  Summary")
        logger.info("=" * 100)
        logger.info("  Total:  %d  |  Success: %d  |  Failed: %d", agg["total"], success, failed)
        if agg["ic_mean"] is not None:
            wr_pct = (agg["winrate"] or 0) * 100
            logger.info("  Avg IC: %+.4f  |  Avg ICIR: %+.4f  |  Avg Winrate: %.1f%%",
                        agg["ic_mean"], agg["icir"], wr_pct)
        if failed:
            logger.info("  Failed alphas:")
            for r in results:
                if r.get("status") == "success":
                    continue
                idx = r.get("alpha_index")
                idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
                logger.info("    alpha-%s: %s - %s",
                            idx_s, r.get("stage", "?"), (r.get("error", "?") or "")[:80])
        logger.info("=" * 100)


class BatchSerializer:
    """JSON / Markdown writers for batch summary."""

    __slots__ = ()

    @staticmethod
    def write_json(results: list[dict], path: Path) -> None:
        """Write batch summary as JSON."""
        agg = BatchAggregator.aggregate(results)
        summary: dict[str, Any] = {
            "total": agg["total"],
            "success_count": agg["success_count"],
            "failed_count": agg["failed_count"],
            "aggregate": {
                "ic_mean_avg": agg["ic_mean"],
                "icir_avg": agg["icir"],
                "winrate_avg": agg["winrate"],
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

    @staticmethod
    def write_markdown(results: list[dict], path: Path) -> None:
        """Write batch summary as Markdown."""
        agg = BatchAggregator.aggregate(results)

        lines: list[str] = [
            "# 101-Alpha Batch Results (v2)",
            "",
            f"- Total: {agg['total']} | Success: {agg['success_count']} | Failed: {agg['failed_count']}",
        ]
        if agg["ic_mean"] is not None:
            wr_pct = (agg["winrate"] or 0) * 100
            lines.append(
                f"- Avg IC: {agg['ic_mean']:+.4f} | Avg ICIR: {agg['icir']:+.4f} | Avg Winrate: {wr_pct:.1f}%"
            )
        lines += [
            "",
            "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |",
            "|-------|--------|----|------|---------|------|---------|",
        ]
        for r in results:
            idx = r.get("alpha_index")
            st: str = r.get("status", "?")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            ic_s = BatchAggregator.format_metric(r.get("ic_mean"), na="NaN")
            icir_s = BatchAggregator.format_metric(r.get("icir"), na="NaN")
            wr = r.get("ic_winrate")
            wr_s = f"{wr * 100:.1f}%" if isinstance(wr, float) and wr == wr else "NaN"
            cc = r.get("code_chars", 0) or 0
            el = r.get("elapsed_sec", 0) or 0
            lines.append(f"| alpha-{idx_s} | {st} | {ic_s} | {icir_s} | {wr_s} | {cc} | {el:.1f}s |")

        failed = [r for r in results if r.get("status") != "success"]
        if failed:
            lines += ["", "## Failed Alphas", ""]
            for r in failed:
                idx = r.get("alpha_index")
                idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
                lines.append(
                    f"- alpha-{idx_s}: `{r.get('stage', '?')}` - {(r.get('error', '?') or '')[:100]}"
                )

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_formula_brief(alpha_index: int, track_b_path: Path) -> tuple[str, str]:
    """Load factor_name and formula_brief from track_b_checkpoint.json."""
    track_b = json.loads(track_b_path.read_text(encoding="utf-8"))
    alpha = next(s for s in track_b["pass1_signals"] if s["index"] == alpha_index)
    return f"alpha-{alpha_index:03d}", alpha["formula_brief"]





# ════════════════════════════════════════════════════════════════════
# Stage 类层级: BaseStage → (PaperStage | MetaStage | FactorRunner → FactorStage)
# ════════════════════════════════════════════════════════════════════


class BaseStage(ABC):
    """所有阶段的抽象基类。

    定义共同的阶段生命周期：label + config + t0 + run() 入口。
    子类必须实现 run()。

    Note: __slots__ 在有 ABC 父类的情况下部分生效（仍保留 __dict__），
    但能阻止新属性的意外添加。
    """

    __slots__ = ("config", "t0")

    label: str = "base"

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.t0: float = 0.0

    @abstractmethod
    def run(self) -> Any:
        """执行阶段，返回阶段产物。"""
        ...

    def _log_start(self) -> None:
        self.t0 = time.monotonic()
        logger.info("[%s] starting", self.label)

    def _log_done(self) -> None:
        elapsed: float = time.monotonic() - self.t0
        logger.info("[%s] done (%.1fs)", self.label, elapsed)


class PaperStage(BaseStage):
    """Stage 1: paper PDF → track_b_checkpoint.json."""

    __slots__ = ()

    label = "paper"

    def run(self) -> Path:
        self._log_start()
        self._validate()
        summary = self._call_orchestrator()
        self._check_summary(summary)
        track_b_path: Path = self._compute_track_b_path()
        self._verify_output(track_b_path)
        self._log_results(summary, track_b_path)
        self._log_done()
        return track_b_path

    def _validate(self) -> None:
        if not self.config.paper_path or not self.config.paper_path.exists():
            raise FileNotFoundError(f"Paper not found: {self.config.paper_path}")

    def _call_orchestrator(self) -> dict:
        from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper
        output_root: Path = self.config.paper_output_root or PROJECT_ROOT / "quant" / "papers"
        logger.info("[paper] Paper: %s", self.config.paper_path)
        logger.info("[paper] Paper ID: %s", self.config.paper_id)
        logger.info("[paper] Output root: %s", output_root)
        logger.info("[paper] Pass 2: %s", self.config.run_pass2)
        return run_one_paper(
            paper_id=self.config.paper_id,
            source_path=self.config.paper_path,
            output_root=output_root,
            run_pass2=self.config.run_pass2,
        )

    def _check_summary(self, summary: dict) -> None:
        if not summary.get("success"):
            logger.warning("[paper] Failed: %s", summary.get("error"))
            raise RuntimeError(f"Paper extraction failed: {summary.get('error')}")

    def _compute_track_b_path(self) -> Path:
        output_root: Path = self.config.paper_output_root or PROJECT_ROOT / "quant" / "papers"
        return output_root / self.config.paper_id / "track_b_checkpoint.json"

    def _verify_output(self, path: Path) -> None:
        if not path.exists():
            logger.warning("[paper] track_b_checkpoint.json not found after extraction")
            raise FileNotFoundError("track_b_checkpoint.json not found after extraction")

    def _log_results(self, summary: dict, track_b_path: Path) -> None:
        logger.info("[paper] Success: %d signals extracted", summary["n_signals"])
        logger.info("[paper] Output: %s", track_b_path)


class MetaStage(BaseStage):
    """Stage 2b: alpha JSONs → L2-L6 metadata."""

    __slots__ = ()

    label = "meta"

    def run(self) -> None:
        self._log_start()
        available: list[int] = self._find_available()
        if not available:
            logger.warning("[meta] No single_factor_NNN.json found in output/")
            logger.warning("[meta] Run Stage 2 first (without --llm-extract)")
            return
        self._log_meta_overview(available)
        results: list[dict] = self._call_extractor(available)
        self._log_done_results(results)
        self._log_done()

    def _find_available(self) -> list[int]:
        indices: list[int] = list(range(self.config.alpha_start, self.config.alpha_end + 1))
        logger.info("[meta] Starting LLM extraction: alpha %d-%d", self.config.alpha_start, self.config.alpha_end)
        logger.info("[meta] Output dir: %s", self.config.output_dir)
        return [i for i in indices if (self.config.output_dir / f"single_factor_{i:03d}.json").exists()]

    def _log_meta_overview(self, available: list[int]) -> None:
        logger.info("[meta] Available: %d alphas with JSON (%s...)", len(available), available[:5])
        logger.info("[meta] L5 hypothesis_testing skipped (requires FastAPI server)")

    def _call_extractor(self, available: list[int]) -> list[dict]:
        from llmwikify.reproduction.factor_extractor import extract_batch
        return extract_batch(available, output_dir=self.config.output_dir, max_workers=3)

    def _log_done_results(self, results: list[dict]) -> None:
        success = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]
        logger.info("[meta] Complete: %d/%d success", len(success), len(results))
        for r in failed:
            logger.warning("[meta] Failed: alpha-%03d: %s", r["alpha_index"], (r.get("error", "?") or "")[:80])


class FactorRunner(BaseStage):
    """单 alpha 因子运行器（封装原 run_one_factor 函数）。

    持有 config + df_pl + data_cache，可独立使用或被 FactorStage 复用。
    """

    __slots__ = ("df_pl", "data_cache")

    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.df_pl: pl.DataFrame | None = None
        self.data_cache: dict[str, pd.DataFrame] | None = None

    @abstractmethod
    def run(self) -> Any:
        """抽象方法。FactorStage 必须实现。"""
        ...

    def run_one_factor(self, alpha_index: int, use_react: bool = True) -> dict:
        """7 步编排（每步调一个单一职责方法）。

        Step 1: _load_formula
        Step 2: _ensure_df_pl (via _load_dataframe_for_alpha)
        Step 3: _generate_code (ReAct or 1-shot)
        Step 4: _save_factor_h5 (already exists)
        Step 5: _run_pipeline_backtest (with _fail_pipeline_result)
        Step 6: _log_backtest_metrics + extract_full_backtest_from_ctx
        Step 7: _persist_factor + _save_to_duckdb (already exist)
        """
        t0: float = time.monotonic()
        config = self.config

        # Step 1: Load formula_brief
        factor_name, formula_brief = self._load_formula(alpha_index)
        logger.info("[alpha-%03d] === formula_brief ===", alpha_index)
        logger.info("[alpha-%03d] %s", alpha_index, formula_brief)

        # Step 2: Ensure df_pl + log shape
        df_pl: pl.DataFrame = self._ensure_df_pl(config)
        logger.info("[alpha-%03d] data: shape=%s, range=%s - %s",
                    alpha_index, df_pl.shape, df_pl['date'].min(), df_pl['date'].max())

        # Step 3: LLM code generation
        logger.info("[alpha-%03d] LLM: %s mode", alpha_index, "ReAct" if use_react else "1-shot")
        code, factor_series, error, stage = self._generate_code(
            factor_name, formula_brief, df_pl, use_react,
        )
        if error is not None:
            logger.warning("[alpha-%03d] failed at %s: %s", alpha_index, stage, error[:100])
            return self._fail_codegen_result(alpha_index, stage, error, code, t0)

        # Step 4: Save factor H5
        factor_wide, h5_path = self._save_factor_h5(factor_series, factor_name, df_pl, config)

        # Step 5: Run backtest
        try:
            ctx = self._run_pipeline_backtest(factor_name, h5_path, code, config)
        except Exception as exc:
            return self._fail_pipeline_result(alpha_index, code, exc, t0)

        # Step 6: Extract metrics + log
        backtest: dict = extract_full_backtest_from_ctx(ctx)
        self._log_backtest_metrics(alpha_index, backtest)

        # Step 7: Persist YAML + DuckDB
        factor_dir = self._persist_factor(factor_name, code, formula_brief, backtest, h5_path, alpha_index, config)
        self._save_to_duckdb(factor_dir, alpha_index, backtest, factor_wide, config)

        # Step 8: Build success result
        return self._success_result(
            alpha_index, factor_name, formula_brief,
            code, factor_series, h5_path, backtest, t0,
        )

    def _load_formula(self, alpha_index: int) -> tuple[str, str]:
        """Step 1: 从 track_b_checkpoint.json 加载 factor_name + formula_brief。"""
        return load_formula_brief(alpha_index, self.config.track_b_path)

    def _generate_code(
        self, factor_name: str, formula_brief: str,
        df_pl: pl.DataFrame, use_react: bool,
    ) -> tuple[str | None, pl.Series | None, str | None, str]:
        """Step 3: LLM 代码生成（ReAct 或 1-shot）。

        Returns:
            (code, factor_series, error, stage):
              - code: 生成的代码（失败时为 None 或部分代码）
              - factor_series: 因子序列（失败时为 None）
              - error: 错误信息（成功时为 None）
              - stage: 失败阶段名（"react" / "llm" / "extract" / "syntax" / "safety" / "execute"）
        """
        llm = build_llm_client()
        if use_react:
            code, factor_series, error, _react_meta = self._llm_code_react(
                factor_name, formula_brief, df_pl, llm, self.config,
            )
            return code, factor_series, error, "react"
        code, factor_series, error, stage_idx = llm_code_oneshot(
            factor_name=factor_name,
            formula_brief=formula_brief,
            df_pl=df_pl,
            llm=llm,
            temperature=self.config.temperature,
        )
        return code, factor_series, error, _STAGE_NAMES.get(stage_idx, "unknown")

    def _fail_codegen_result(
        self, alpha_index: int, stage: str, error: str,
        code: str | None, t0: float,
    ) -> dict:
        """Step 3 failure: 构造 codegen 失败的统一 result dict（见 P3 Bug 5 字段约定）。"""
        return {
            "status": "failed",
            "stage": stage,
            "error": error,
            "code": code,
            "code_chars": len(code) if code else 0,
            "ic_mean": None,
            "icir": None,
            "ic_winrate": None,
            "elapsed_sec": time.monotonic() - t0,
        }

    def _fail_pipeline_result(
        self, alpha_index: int, code: str, exc: Exception, t0: float,
    ) -> dict:
        """Step 5 failure: 构造 pipeline 失败的统一 result dict（带 traceback[-1500:]）。"""
        import traceback
        tb: str = traceback.format_exc()
        logger.warning("[alpha-%03d] failed at pipeline: %s: %s",
                       alpha_index, type(exc).__name__, str(exc)[:100])
        return {
            "status": "failed",
            "stage": "pipeline",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": tb[-1500:],
            "code": code,
            "code_chars": len(code) if code else 0,
            "ic_mean": None,
            "icir": None,
            "ic_winrate": None,
            "elapsed_sec": time.monotonic() - t0,
        }

    def _log_backtest_metrics(self, alpha_index: int, backtest: dict) -> None:
        """Step 6: 输出 backtest 指标日志（IC / ICIR / WinRate）。"""
        logger.info("[alpha-%03d] backtest: IC=%.4f, ICIR=%.4f, WinRate=%.1f%%",
                    alpha_index,
                    backtest.get("ic_mean", 0),
                    backtest.get("icir", 0),
                    (backtest.get("win_rate", 0) or 0) * 100)

    def _success_result(
        self, alpha_index: int, factor_name: str, formula_brief: str,
        code: str, factor_series: pl.Series, h5_path: Path,
        backtest: dict, t0: float,
    ) -> dict:
        """Step 7-8: 构造成功 result dict。"""
        elapsed: float = time.monotonic() - t0
        logger.info("[alpha-%03d] success (%.1fs)", alpha_index, elapsed)
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

    def _fail_result(
        self, alpha_index: int, stage: str, error: str,
        t0: float, *, code: str | None = None, **extra: Any,
    ) -> dict:
        """统一失败 result 工厂（P3 Bug 5 复用：_handle_parallel_failure 用此）。

        Args:
            alpha_index: alpha index
            stage: 失败阶段名
            error: 错误信息
            t0: 起始时间（monotonic）
            code: 失败时已生成的 code（可能 None）
            **extra: 额外字段（如 traceback / react_meta）
        """
        result: dict = {
            "status": "failed",
            "alpha_index": alpha_index,
            "stage": stage,
            "error": error,
            "code": code,
            "code_chars": len(code) if code else 0,
            "ic_mean": None,
            "icir": None,
            "ic_winrate": None,
            "elapsed_sec": time.monotonic() - t0,
        }
        result.update(extra)
        return result

    def _ensure_df_pl(self, config: RunConfig) -> pl.DataFrame:
        if self.df_pl is not None:
            return self.df_pl
        if self.data_cache is not None:
            self.df_pl = build_long_dataframe(self.data_cache)
            return self.df_pl
        self.df_pl = load_and_build_df(config.data_path, config.h5_filename)
        return self.df_pl

    def _save_factor_h5(
        self, factor_series: pl.Series, factor_name: str,
        df_pl: pl.DataFrame, config: RunConfig,
    ) -> tuple[pl.DataFrame, Path]:
        unique_vals = factor_series.drop_nulls().unique()
        if len(unique_vals) <= 2:
            logger.warning("[alpha] constant/binary factor detected (%d unique values), adding noise", len(unique_vals))
            noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(factor_series)))
            factor_series = factor_series.cast(pl.Float64) + noise
        factor_wide = wide_from_long(df_pl, factor_series)
        logger.info("[alpha] h5: wide shape=%s, range=%s - %s",
                    factor_wide.shape, factor_wide.index.min(), factor_wide.index.max())
        safe_factor_name: str = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
        h5_path = write_factor_h5(factor_wide, safe_factor_name, config.data_path)
        logger.info("[alpha] h5: written %s", h5_path)
        return factor_wide, h5_path

    def _llm_code_react(
        self, factor_name: str, formula_brief: str,
        df_pl: pl.DataFrame, llm: Any, config: RunConfig,
    ) -> tuple[str | None, pl.Series | None, str | None, dict]:
        from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code_sync

        class _ProgressHook(UnifiedHook):
            def on_reason_start(self, ctx: Any) -> None:
                logger.info("[REASON] iteration %s...", ctx.iteration)

            def on_act_end(self, ctx: Any, result: Any) -> None:
                if hasattr(result, "success") and result.success:
                    logger.info("[ACT] OK (%s)", getattr(result, "error_kind", "none"))
                else:
                    ek = getattr(result, "error_kind", "unknown")
                    em = (getattr(result, "error", "") or "")[:120]
                    logger.info("[ACT] %s: %s", ek, em)

        result = generate_factor_code_sync(
            factor_name=factor_name,
            formula_brief=formula_brief,
            df=df_pl,
            llm_client=llm,
            max_repair_rounds=config.max_repair_rounds,
            temperature=config.temperature,
            hook=_ProgressHook(),
        )

        logger.info("[Unified] iterations=%s, stop_reason=%s, error=%s",
                    result.iterations, result.stop_reason, result.error)

        if result.error:
            return None, None, result.error, result.to_dict()
        return result.code, result.factor_series, None, result.to_dict()

    def _run_pipeline_backtest(
        self, factor_name: str, h5_path: Path, code: str, config: RunConfig,
    ) -> dict:
        from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner
        from llmwikify.reproduction.pipeline.backtest_config import build_qn_config
        qn_config = build_qn_config(factor_name, h5_path, code, config=config)
        logger.info("[PipelineRunner] building config + running 12-node pipeline")
        runner = PipelineRunner.from_dict(qn_config)
        return runner.run()

    def _persist_factor(
        self, factor_name: str, code: str, formula_brief: str,
        backtest: dict, h5_path: Path, alpha_index: int, config: RunConfig,
    ) -> Path | None:
        from llmwikify.reproduction.pipeline.persist import persist_code_to_yaml
        _, factor_dir = persist_code_to_yaml(
            factor_name=factor_name,
            code=code,
            formula_brief=formula_brief,
            backtest=backtest,
            h5_path=str(h5_path),
            code_chars=len(code),
            config=config,
            alpha_index=alpha_index,
        )
        return factor_dir

    def _save_to_duckdb(
        self, factor_dir: Path | None, alpha_index: int,
        backtest: dict, factor_wide: pl.DataFrame, config: RunConfig,
    ) -> None:
        from llmwikify.reproduction.persist.factor_library import save_backtest_duckdb
        run_id: str = f"pipeline_a_{alpha_index:03d}"
        if factor_dir:
            rel_path: str = str(factor_dir.relative_to(config.factors_dir))
        else:
            rel_path = f"alpha_{alpha_index:03d}"
        save_backtest_duckdb(
            factor_name=rel_path,
            run_id=run_id,
            backtest=backtest,
            factor_wide=factor_wide,
            factors_dir=config.factors_dir,
        )


class FactorStage(FactorRunner):
    """Stage 2: 批量 alpha 处理（继承 FactorRunner 复用 run_one_factor）。

    复用 v1 重复逻辑（方案 A+B+C）:
    - 提取 _run_one_with_recording（共享 run + record）
    - 拆分 _record_result 为 _update_state / _persist_result / _log_outcome
    - batch_t0 区分批量计时与生命周期计时
    """

    __slots__ = ("results", "failures", "batch_t0")

    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.results: list[dict] = []
        self.failures: int = 0
        self.batch_t0: float = 0.0

    def run(self) -> list[dict]:
        """批量执行入口。"""
        self._log_start()
        self._log_config()
        BatchReporter.log_banner()
        self.batch_t0 = time.monotonic()
        self._preload_data()
        skip: set[int] = self._process_skip_existing()
        to_run: list[int] = self._compute_to_run(skip)
        logger.info("[factor] To run: %d alphas", len(to_run))
        if self.config.workers <= 1:
            self._run_serial(to_run)
        else:
            self._run_parallel(to_run)
        self._write_summary()
        self._log_done()
        return self.results

    def _log_config(self) -> None:
        logger.info("[factor] Data path: %s", self.config.data_path)
        logger.info("[factor] Track B: %s", self.config.track_b_path)
        logger.info("[factor] Date range: %d - %d", self.config.date_beg, self.config.date_end)
        logger.info("[factor] Sample index: %s", self.config.sample_index)
        logger.info("[factor] H5 filename: %s", self.config.h5_filename)
        logger.info("[factor] Workers: %d", self.config.workers)

    def _preload_data(self) -> None:
        self.data_cache = preload_market_data(self.config.data_path, self.config.h5_filename)
        logger.info("[factor] Preloaded %d H5 keys: %s",
                    len(self.data_cache), list(self.data_cache.keys()))
        self.df_pl = build_long_dataframe(self.data_cache)
        logger.info("[factor] Built polars long DF: %s", self.df_pl.shape)

    def _process_skip_existing(self) -> set[int]:
        """Scan output_dir, return set of idx to skip (and load their cached results)."""
        skip: set[int] = set()
        if not self.config.skip_existing:
            return skip
        for idx in range(self.config.alpha_start, self.config.alpha_end + 1):
            p = self.config.output_dir / f"single_factor_{idx:03d}.json"
            if p.exists():
                skip.add(idx)
        if skip:
            logger.info("[factor] Skipping %d alphas: %s...", len(skip), sorted(skip)[:10])
            self._load_skipped_results(skip)
        return skip

    def _load_skipped_results(self, skip: set[int]) -> None:
        """Load JSON results for skipped alphas.

        Bug 6 fix: skip corrupt JSON instead of crashing the batch.
        """
        for idx in sorted(skip):
            p = self.config.output_dir / f"single_factor_{idx:03d}.json"
            try:
                loaded: dict = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[factor] skip-corrupt: alpha-%03d: %s", idx, exc)
                continue
            if "alpha_index" not in loaded:
                loaded["alpha_index"] = idx
            self.results.append(loaded)

    def _compute_to_run(self, skip: set[int]) -> list[int]:
        """Return alpha indices to run (excluding skipped ones)."""
        return [idx for idx in range(self.config.alpha_start, self.config.alpha_end + 1)
                if idx not in skip]

    def _run_one_with_recording(self, idx: int) -> dict:
        """Serial 路径：单线程，无需锁。

        调用链: run_one_factor → _record_one (atomic)
        """
        elapsed_cum: float = time.monotonic() - self.batch_t0
        logger.info("[factor] alpha-%03d: starting (elapsed: %.0fs, failures: %d)",
                    idx, elapsed_cum, self.failures)
        result = self.run_one_factor(idx, use_react=True)
        self._record_one(idx, result, elapsed_cum)
        return result

    def _run_serial(self, to_run: list[int]) -> None:
        for idx in to_run:
            self._run_one_with_recording(idx)
            if self._reached_max_failures():
                break
            self._inter_alpha_delay(idx)

    def _run_parallel(self, to_run: list[int]) -> None:
        logger.info("[factor] Using %d concurrent workers", self.config.workers)
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = {pool.submit(self._run_one_safe, idx): idx for idx in to_run}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result(timeout=self.config.timeout + 60)
                except Exception as exc:
                    import traceback
                    tb = traceback.format_exc()
                    self._handle_parallel_failure(idx, type(exc).__name__,
                                                  f"{exc}\n{tb[-500:]}")

    def _handle_parallel_failure(self, idx: int, stage: str, error: str) -> None:
        """Append a synthetic failed result so Total = Success + Failed stays consistent.

        Called from _run_parallel when future.result() raises (i.e., _run_one_safe
        crashed before _update_state could append to self.results).

        P3 Bug 5 修复：synthetic result 复用 _fail_result 工厂，字段全（含 code_chars）。
        """
        result = self._fail_result(
            alpha_index=idx,
            stage=stage,
            error=error[:200],
            t0=time.monotonic(),
        )
        self.results.append(result)
        self.failures += 1
        logger.warning("[factor] alpha-%03d: EXCEPTION (%s): %s", idx, stage, error[:100])

    def _run_one_safe(self, idx: int) -> dict:
        """Parallel 路径：_llm_semaphore + _print_lock 包住 record。

        Lock placement (mimics v1, Bug 3 修复后保持):
          - _llm_semaphore (max 3 concurrent LLM calls to api.minimaxi.com)
          - _print_lock only around _record_one (state + log + JSON write)
            (NOT around the LLM call itself, to avoid serializing the 3 workers)

        Bug 8 回归: _record_one 内 _persist_result 在 _print_lock 内串行 IO
        是有意的 — 防止 3 workers 同时写 JSON 时错位（与 Bug 3 修复一致）。
        """
        with _llm_semaphore:
            result = self.run_one_factor(idx, use_react=True)
            elapsed_cum = time.monotonic() - self.batch_t0
            with _print_lock:
                self._record_one(idx, result, elapsed_cum)
            return result

    def _record_one(self, idx: int, result: dict, elapsed_cum: float) -> None:
        """Atomic record: state + row log + persist + outcome.

        共享给 serial (_run_one_with_recording) 和 parallel (_run_one_safe) 路径。
        调用方负责锁包装（serial 无锁，parallel 在 _print_lock 内）。
        """
        self._update_state(idx, result)
        BatchReporter.log_row(idx, result, elapsed_cum)
        self._persist_result(idx, result)
        self._log_outcome(idx, result)

    def _update_state(self, idx: int, result: dict) -> None:
        """Update in-memory state: results list + failure counter."""
        if "alpha_index" not in result:
            result["alpha_index"] = idx
        self.results.append(result)
        if result.get("status") != "success":
            self.failures += 1

    def _persist_result(self, idx: int, result: dict) -> None:
        """Write single alpha JSON to output_dir."""
        out_file = self.config.output_dir / f"single_factor_{idx:03d}.json"
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def _log_outcome(self, idx: int, result: dict) -> None:
        """Log success or failure for one alpha."""
        if result.get("status") != "success":
            logger.warning("[factor] alpha-%03d: failed (%s)", idx, (result.get("error", "?") or "")[:80])
        else:
            logger.info("[factor] alpha-%03d: success (%.1fs)", idx, result.get("elapsed_sec", 0))

    def _reached_max_failures(self) -> bool:
        if self.failures >= self.config.max_failures:
            logger.warning("[factor] Reached max failures (%d), stopping", self.config.max_failures)
            return True
        return False

    def _inter_alpha_delay(self, idx: int) -> None:
        """Sleep between alpha runs (if not last and delay > 0 and --no-delay not set)."""
        if idx < self.config.alpha_end and self.config.delay > 0 and not self.config.no_delay:
            time.sleep(self.config.delay)

    def _write_summary(self) -> None:
        BatchSerializer.write_json(self.results, self.config.output_dir / "multi_alpha_001_to_101.json")
        BatchSerializer.write_markdown(self.results, self.config.output_dir / "multi_alpha_summary.md")
        BatchReporter.log_summary(self.results)
        total_elapsed: float = time.monotonic() - self.batch_t0
        logger.info("[factor] Total elapsed: %.1fs (%.1f min)", total_elapsed, total_elapsed / 60)
        logger.info("[factor] Results saved to: %s", self.config.output_dir)


def main() -> None:
    global logger

    parser = argparse.ArgumentParser(description="Batch run 101 alphas (v2)")

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
    parser.add_argument("--log-file", type=Path, default=None, help="Log file path (default: scripts/output/run_101_alphas_v2.log)")
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
    log_path: Path = Path(args.log_file) if args.log_file else PROJECT_ROOT / "scripts" / "output" / "run_101_alphas_v2.log"
    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO,
        log_dir=log_path.parent,
        log_file=log_path.name,
        force=True,
    )
    logger = logging.getLogger("run_101_alphas_v2")

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
        track_b_path = PaperStage(config).run()

    # Update config with resolved track_b_path
    if track_b_path:
        config = replace(config, track_b_path=track_b_path)

    # ── Stage 2: Factor processing ──
    if not config.llm_extract:
        FactorStage(config).run()

    # ── Stage 2b: LLM metadata extraction ──
    if config.llm_extract:
        MetaStage(config).run()


if __name__ == "__main__":
    main()
