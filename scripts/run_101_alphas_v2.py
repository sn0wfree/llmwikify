"""Run all 101 alphas in batch mode — v2 (recipe-based refactor).

PR6: v2 rewired to use the new modular framework (PR1-PR5). Internals are
now thin re-exports / shims; the heavy lifting is in:
  - llmwikify.reproduction.core         (PaperPipeline, PaperRecipe)
  - llmwikify.reproduction.signal_source (TrackBSignalSource for 101 alphas)
  - llmwikify.reproduction.backtest      (QuantNodesBacktest)
  - llmwikify.reproduction.sink         (SingleJsonSink, YamlDuckdbSink, BatchSummarySink)
  - llmwikify.reproduction.reporting    (BatchAggregator, BatchReporter, BatchSerializer)
  - llmwikify.reproduction.data_source.akshare_h5 (AkShareH5DataSource)

CLI args + output file names/contents are byte-equal to pre-PR6 v2:
  - output_dir/single_factor_<NNN>.json     (one per alpha)
  - output_dir/multi_alpha_001_to_101.json  (batch summary)
  - output_dir/multi_alpha_summary.md       (batch summary table)
  - factors_dir/<strategy_dir>/stk_alpha_NNN_HASH/factor.{yaml,duckdb}

Usage:
  python scripts/run_101_alphas_v2.py                  # run all
  python scripts/run_101_alphas_v2.py --start 1 --end 5
  python scripts/run_101_alphas_v2.py --skip-existing
  python scripts/run_101_alphas_v2.py --max-failures 5

设计文档: docs/designs/run_101_alphas_v2_design.md (§17.6 PR6)
"""
from __future__ import annotations

__all__ = [
    # Config
    "RunConfig",
    # Base classes
    "BaseStage",
    # Concrete stages (shims — kept for backward compat)
    "PaperStage",
    "MetaStage",
    "FactorRunner",
    "FactorStage",
    # Reporting (re-exported from reporting/)
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
import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import polars as pl

from llmwikify.apps.chat.agent.unified.core import UnifiedHook
from llmwikify.foundation.logging import log_timing, setup_logging

# L2: FactorResult imported at top (was inside methods in PR6).
from llmwikify.reproduction.backtest.base import FactorResult
from llmwikify.reproduction.codegen.llm_code import (
    SYSTEM_PROMPT_CODE,
    build_llm_client,
    execute_code,
    extract_python,
    validate_safety,
    validate_syntax,
)

# L1: ReAct codegen moved out (PR8). Re-exported here for backward compat.
from llmwikify.reproduction.codegen.react_runner import (  # noqa: F401
    ReActProgressHook,
    llm_code_react,
)
from llmwikify.reproduction.factor import (
    ResultFactory,  # PR9a: extracted L2 result factories
)
from llmwikify.reproduction.pipeline.backtest_extract import safe_float
from llmwikify.reproduction.pipeline.data_loader import (
    derive_input_columns,
    load_and_build_df,
    wide_from_long,
    write_factor_h5,
)
from llmwikify.reproduction.pipeline.score import compute_score, compute_status
from llmwikify.reproduction.pipeline.stages.codegen import llm_code_oneshot
from llmwikify.reproduction.reporting.aggregator import BatchAggregator
from llmwikify.reproduction.reporting.reporter import BatchReporter
from llmwikify.reproduction.reporting.serializer import BatchSerializer

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
_llm_semaphore = __import__("threading").Semaphore(3)  # api.minimaxi.com ≤3 并发
_print_lock = __import__("threading").Lock()


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
    strategy_dir: str = "101_alphas"
    asset_type: str = "stock"
    category: str = "formulaic"
    frequency: str = "日频"
    nan_meaning: str = "上市不足或窗口期数据不足"
    business_constraints: str = "支持日频调仓, T+1 信号"
    pass_threshold: int = 60
    hedge: str = "equal"
    adj_mode: str = "M-end"
    groups: int = 5
    factor_direction: int = 1
    output_format: list[str] = field(default_factory=lambda: ["parquet", "json"])
    min_group_size: int = 3

    # ── Stage 1: Paper extraction ──
    paper_path: Path | None = None
    paper_output_root: Path | None = None
    run_pass2: bool = True

    # ── Stage 2: Factor processing ──
    alpha_start: int = 1
    alpha_end: int = 101
    skip_existing: bool = False
    max_failures: int = 999
    delay: float = 3.0
    no_delay: bool = False
    timeout: int = 180
    workers: int = 1

    # ── Stage 2b: LLM extraction ──
    llm_extract: bool = False

    # ── Logging ──
    log_file: Path | None = None

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


# ─── Data loading (re-exported from scripts for backward compat) ──────


def preload_market_data(data_path: Path, h5_filename: str = "stk_daily.h5") -> dict:
    """Load all H5 keys once → dict of wide DataFrames.

    Kept here for backward compat (legacy imports).
    New code should use llmwikify.reproduction.data_source.akshare_h5.AkShareH5DataSource.
    """
    import json as _json

    import pandas as pd
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
def build_long_dataframe(data_cache: dict) -> pl.DataFrame:
    """Convert cached wide DataFrames → single polars long DataFrame."""
    def wide_to_long(wide, name: str) -> pl.DataFrame:
        long = wide.stack().reset_index()
        long.columns = ["date", "code", name]
        return pl.from_pandas(long)

    result = wide_to_long(data_cache["close"], "close")
    for col in ("open", "high", "low", "volume", "returns", "vwap", "industry"):
        result = result.join(wide_to_long(data_cache[col], col), on=["date", "code"])
    return result.sort(["date", "code"])


def _make_factor_dir_name(alpha_index: int, code: str) -> str:
    """Dead code per user request: not deleted, kept as utility."""
    code_hash = hashlib.md5(code.encode()).hexdigest()[:6]
    return f"stk_alpha_{alpha_index:03d}_{code_hash}"


def load_formula_brief(alpha_index: int, track_b_path: Path) -> tuple[str, str]:
    """Load factor_name and formula_brief from track_b_checkpoint.json.

    Re-exported for backward compat. New code should use
    llmwikify.reproduction.signal_source.track_b.TrackBSignalSource.
    """
    import json as _json
    track_b = _json.loads(track_b_path.read_text(encoding="utf-8"))
    alpha = next(s for s in track_b["pass1_signals"] if s["index"] == alpha_index)
    return f"alpha-{alpha_index:03d}", alpha["formula_brief"]


# Note: ReActProgressHook + llm_code_react imported at top (see L1 re-export)

# ════════════════════════════════════════════════════════════════════
# Stage classes (shims — kept for backward compat)
# ════════════════════════════════════════════════════════════════════


class BaseStage(ABC):
    """Base stage abstract class (shim — re-exported from core)."""

    __slots__ = ("config", "t0")
    label: str = "base"

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.t0: float = 0.0

    @abstractmethod
    def run(self) -> Any: ...

    def _log_start(self) -> None:
        self.t0 = time.monotonic()
        logger.info("[%s] starting", self.label)

    def _log_done(self) -> None:
        elapsed: float = time.monotonic() - self.t0
        logger.info("[%s] done (%.1fs)", self.label, elapsed)


class PaperStage(BaseStage):
    """Stage 1: paper PDF → track_b_checkpoint.json (shim)."""

    __slots__ = ()
    label = "paper"

    def run(self) -> Path:
        from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import (
            run_one_paper,
        )
        self._log_start()
        if not self.config.paper_path or not self.config.paper_path.exists():
            raise FileNotFoundError(f"Paper not found: {self.config.paper_path}")
        output_root: Path = self.config.paper_output_root or PROJECT_ROOT / "quant" / "papers"
        logger.info("[paper] Paper: %s", self.config.paper_path)
        summary = run_one_paper(
            paper_id=self.config.paper_id,
            source_path=self.config.paper_path,
            output_root=output_root,
            run_pass2=self.config.run_pass2,
        )
        if not summary.get("success"):
            raise RuntimeError(f"Paper extraction failed: {summary.get('error')}")
        track_b_path: Path = output_root / self.config.paper_id / "track_b_checkpoint.json"
        if not track_b_path.exists():
            raise FileNotFoundError("track_b_checkpoint.json not found after extraction")
        logger.info("[paper] Success: %d signals extracted", summary["n_signals"])
        self._log_done()
        return track_b_path


class MetaStage(BaseStage):
    """Stage 2b: alpha JSONs → L2-L6 metadata (shim)."""

    __slots__ = ()
    label = "meta"

    def run(self) -> None:
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
        """Backward-compat shim (Bug 9 test fixture). Uses os.scandir."""
        import os as _os
        indices: list[int] = list(range(self.config.alpha_start, self.config.alpha_end + 1))
        logger.info("[meta] Starting LLM extraction: alpha %d-%d", self.config.alpha_start, self.config.alpha_end)
        logger.info("[meta] Output dir: %s", self.config.output_dir)
        try:
            with _os.scandir(self.config.output_dir) as it:
                existing = {e.name for e in it if e.is_file()}
        except FileNotFoundError:
            return []
        return [i for i in indices if f"single_factor_{i:03d}.json" in existing]

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
    """Single alpha runner (shim — kept for backward compat).

    PR6: class retained for legacy imports. Heavy internals (run_one_factor,
    _load_formula, _generate_code, etc.) are no longer used internally —
    see FactorStage below for the new recipe-based orchestration, or use
    the new llmwikify.reproduction.core.PaperPipeline directly.

    Backward-compat methods retained: _fail_result (used by Bug 5 test
    and other legacy callers).
    """

    __slots__ = ("df_pl", "data_cache")
    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.df_pl: pl.DataFrame | None = None
        self.data_cache: dict | None = None

    @abstractmethod
    def run(self) -> Any: ...

    def _fail_result(
        self,
        alpha_index: int, stage: str, error: str,
        t0: float, *, code: str | None = None, **extra: Any,
    ) -> dict:
        """Backward-compat shim (Bug 5 test fixture). Returns the same dict
        shape that pre-PR6 v2 produced."""
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

    def _generate_code(
        self, factor_name: str, formula_brief: str,
        df_pl: pl.DataFrame, use_react: bool = True,
    ) -> tuple[str | None, pl.Series | None, str | None, str]:
        """Backward-compat shim (PR0 test fixture). ReAct or 1-shot codegen."""
        llm = build_llm_client()
        if use_react:
            code, factor_series, error, _react_meta = self._llm_code_react(
                factor_name, formula_brief, df_pl, llm,
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

    def _llm_code_react(
        self, factor_name: str, formula_brief: str,
        df_pl: pl.DataFrame, llm: Any,
    ) -> tuple[str | None, pl.Series | None, str | None, dict]:
        """Backward-compat shim (PR0 test fixture). Thin wrapper around new top-level llm_code_react (L1: no RunConfig dep)."""
        return llm_code_react(
            factor_name, formula_brief, df_pl, llm,
            max_repair_rounds=self.config.max_repair_rounds,
            temperature=self.config.temperature,
        )

    def _load_formula(self, alpha_index: int) -> tuple[str, str]:
        """Backward-compat shim (PR0 test fixture). Step 1 of run_one_factor."""
        return load_formula_brief(alpha_index, self.config.track_b_path)

    def _log_backtest_metrics(self, alpha_index: int, backtest: dict) -> None:
        """Backward-compat shim (PR0 test fixture)."""
        logger.info(
            "[alpha-%03d] backtest: IC=%.4f, ICIR=%.4f, WinRate=%.1f%%",
            alpha_index,
            backtest.get("ic_mean", 0),
            backtest.get("icir", 0),
            (backtest.get("win_rate", 0) or 0) * 100,
        )

    def _success_result(
        self, alpha_index: int, factor_name: str, formula_brief: str,
        code: str, factor_series: pl.Series, h5_path: Path,
        backtest: dict, t0: float,
    ) -> dict:
        """Backward-compat shim (PR0 test fixture). Build success result dict."""
        elapsed: float = time.monotonic() - t0
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

    def _fail_codegen_result(
        self, alpha_index: int, stage: str, error: str,
        code: str | None, t0: float,
    ) -> dict:
        """Backward-compat shim (PR0 test fixture). Build codegen-fail result dict."""
        return {
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

    def _fail_pipeline_result(
        self, alpha_index: int, code: str, exc: Exception, t0: float,
    ) -> dict:
        """Backward-compat shim (PR0 test fixture). Build pipeline-fail result dict."""
        import traceback
        tb: str = traceback.format_exc()
        return {
            "status": "failed",
            "alpha_index": alpha_index,
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

    # ── L2: FactorResult-returning variants (used by FactorStage internally) ──
    # PR9a: moved to `llmwikify.reproduction.factor.ResultFactory`.
    # Use `self._factory.success(...)` etc. (initialized in FactorStage.__init__).


class FactorStage(FactorRunner):
    """Stage 2: batch alpha processing (shim — orchestrates PaperPipeline).

    PR6: replaced class internals with PaperRecipe + PaperPipeline (PR1).
    Kept as a class for backward compat (legacy code can still call
    `FactorStage(config).run()`). All actual work delegated to the
    modular framework.
    """

    __slots__ = ("results", "batch_t0", "_single_sink", "_yaml_sink", "_summary_sink", "_factory", "_record_stage", "_failures_ref", "_engine")
    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        # L2: state now stores FactorResult objects (not dicts) so that
        # Sinks can be called directly without dict→FactorResult conversion.
        self.results: list[FactorResult] = []
        # PR9c: failures is now a property reading self._failures_ref[0]
        # (Python has no mutable int; RecordStage mutates the [0] slot).
        self._failures_ref: list[int] = [0]
        self.batch_t0: float = 0.0
        # PR6: sinks (lazy-init in run() OR _write_single_json)
        self._single_sink: Any = None
        self._yaml_sink: Any = None
        self._summary_sink: Any = None
        # PR9a: shared result factory (extracted from FactorRunner's L2 methods)
        self._factory: ResultFactory = ResultFactory()
        # PR9c: record stage (per-signal state + log + persist + outcome)
        # Lazily inited in run() because it needs _single_sink.
        self._record_stage: Any = None
        # PR9c L4: QuantNodes backtest engine (replaces inline backtest).
        self._engine: Any = None  # QuantNodesBacktest, lazy import in run()

    @property
    def failures(self) -> int:
        """PR9c: read-only view into _failures_ref[0] (mutable int wrapper)."""
        return self._failures_ref[0]

    def run(self) -> list[FactorResult]:
        """Orchestrate batch alpha processing using the new modular sinks.

        PR6: Same control flow as pre-PR6 v2 (skip_existing / serial / parallel
        / write_summary), but persistence delegated to the new Sinks:
          - SingleJsonSink     → single_factor_NNN.json
          - YamlDuckdbSink     → factors/<dir>/factor.{yaml,duckdb}
          - BatchSummarySink   → multi_alpha_001_to_101.{json,md}

        L2: Returns list[FactorResult] (was list[dict]). Sinks can be called
        directly with these objects, no manual dict→FactorResult conversion.
        """
        self._log_start()
        self.batch_t0 = time.monotonic()
        BatchReporter.log_banner()

        # PR6: instantiate the 3 new sinks (PR4) — replaces inline writes
        from llmwikify.reproduction.sink import (
            BatchSummarySink,
            SingleJsonSink,
            YamlDuckdbSink,
        )
        self._single_sink = SingleJsonSink(output_dir=self.config.output_dir)
        self._yaml_sink = YamlDuckdbSink(
            factors_dir=self.config.factors_dir,
            strategy_dir=self.config.strategy_dir,
            config=self.config,
        )
        self._summary_sink = BatchSummarySink(
            output_dir=self.config.output_dir,
            paper_id=self.config.paper_id,
            json_filename="multi_alpha_001_to_101.json",  # v2-specific name
            md_filename="multi_alpha_summary.md",         # v2-specific name
        )
        # PR9c: initialize record stage (per-signal state + log + persist + outcome)
        from llmwikify.reproduction.factor import RecordStage
        self._record_stage = RecordStage(
            single_sink=self._single_sink,
            results=self.results,
            failures=self._failures_ref,
        )
        # PR9c L4: initialize QuantNodes backtest engine (replaces inline backtest)
        from llmwikify.reproduction.backtest import QuantNodesBacktest
        self._engine = QuantNodesBacktest(config=self.config)

        self._log_config()
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
        """Preload H5 keys (legacy v2 step — now AkShareH5DataSource handles it)."""
        if self.data_cache is None and self.config.data_path:
            self.data_cache = preload_market_data(
                self.config.data_path, self.config.h5_filename,
            )
            logger.info("[factor] Preloaded %d H5 keys", len(self.data_cache))

    def _process_skip_existing(self) -> set[int]:
        """PR9b: delegate to SkipLoader (was inline logic).

        Returns:
            Set of idx with cached results. Side effect: appends cached
            FactorResults to self.results.
        """
        from llmwikify.reproduction.factor import SkipLoader

        loader = SkipLoader(
            output_dir=self.config.output_dir,
            alpha_start=self.config.alpha_start,
            alpha_end=self.config.alpha_end,
            skip_existing=self.config.skip_existing,
        )
        skip = loader.scan()
        if skip:
            logger.info(
                "[factor] Skipping %d alphas: %s...",
                len(skip), sorted(skip)[:10],
            )
            self.results.extend(loader.load(skip, self._factory))
        return skip

    def _compute_to_run(self, skip: set[int]) -> list[int]:
        """Return alpha indices to run (excluding skipped ones)."""
        return [idx for idx in range(self.config.alpha_start, self.config.alpha_end + 1)
                if idx not in skip]

    def _run_one_with_codegen(self, idx: int) -> FactorResult:
        """Run single alpha: codegen + backtest + sinks, mirroring v2's run_one_factor flow.

        L2: Returns FactorResult (was dict). State stored in self.results
        matches Sinks' contract — no dict→FactorResult conversion needed.
        """
        return self.run_one_factor(idx)

    def run_one_factor(self, idx: int) -> FactorResult:
        """Backward-compat alias for _run_one_with_codegen (PR0 test fixture).

        Old tests use `patch.object(FactorStage, 'run_one_factor', ...)` —
        keep the method name so patches work. Tests return FactorResult
        mocks (PR0 tests updated to FactorResult in L2).
        """
        import traceback
        t0 = time.monotonic()
        try:
            config = self.config
            # Step 1: load formula
            factor_name, formula_brief = load_formula_brief(idx, config.track_b_path)
            logger.info("[alpha-%03d] formula_brief: %s", idx, formula_brief[:80])
            # Step 2: ensure df_pl
            df_pl = self.df_pl
            if df_pl is None:
                self._preload_data()
                df_pl = build_long_dataframe(self.data_cache)
                self.df_pl = df_pl
            # Step 3: LLM codegen (ReAct)
            code, factor_series, error, stage = self._generate_code(
                factor_name, formula_brief, df_pl,
            )
            if error is not None:
                logger.warning("[alpha-%03d] failed at %s: %s", idx, stage, error[:100])
                # PR9a: result factory (was _fail_codegen_fr)
                result: FactorResult = self._factory.fail_codegen(
                    alpha_index=idx, stage=stage, error=error, code=code, t0=t0,
                )
            else:
                # Step 4: H5 + Step 5: backtest + Step 6: metrics
                import re

                import numpy as np
                unique_vals = factor_series.drop_nulls().unique()
                if len(unique_vals) <= 2:
                    logger.warning("[alpha] constant/binary factor detected (%d unique values), adding noise", len(unique_vals))
                    noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(factor_series)))
                    factor_series = factor_series.cast(pl.Float64) + noise
                factor_wide = wide_from_long(df_pl, factor_series)
                safe_factor_name = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
                h5_path = write_factor_h5(factor_wide, safe_factor_name, config.data_path)
                logger.info("[alpha] h5: written %s", h5_path)
                # PR9c L4-minimal: delegate backtest to QuantNodesBacktest (PR3).
                # engine.run() handles the QuantNodes pipeline internally and
                # returns metrics dict (or {"error": ...} on failure).
                backtest_signal = self._factory.build_signal(idx, factor_name, formula_brief)
                backtest = self._engine.run(
                    code=code, h5_path=h5_path, signal=backtest_signal,
                )
                if backtest.get("error"):
                    logger.warning(
                        "[alpha-%03d] failed at pipeline: %s",
                        idx, backtest["error"][:100],
                    )
                    # PR9a: result factory (was _fail_pipeline_fr)
                    result = self._factory.fail_pipeline(
                        alpha_index=idx, code=code,
                        exc=RuntimeError(backtest["error"]), t0=t0,
                    )
                else:
                    logger.info(
                        "[alpha-%03d] backtest: IC=%.4f, ICIR=%.4f, WinRate=%.1f%%",
                        idx, backtest.get("ic_mean", 0), backtest.get("icir", 0),
                        (backtest.get("win_rate", 0) or 0) * 100,
                    )
                    # PR9a: result factory (was _success_fr)
                    success_fr = self._factory.success(
                        alpha_index=idx, factor_name=factor_name,
                        formula_brief=formula_brief, code=code,
                        factor_series=factor_series, h5_path=h5_path,
                        backtest=backtest, t0=t0,
                    )
                    # Step 7: persist YAML + DuckDB via YamlDuckdbSink (PR4)
                    self._persist_via_sink(success_fr)
                    result = success_fr
                    logger.info("[alpha-%03d] success (%.1fs)", idx, time.monotonic() - t0)
            return result
        except Exception as exc:
            logger.warning("[alpha-%03d] EXCEPTION: %s: %s", idx, type(exc).__name__, str(exc)[:100])
            # PR9a: result factory (was _fail_codegen_fr)
            return self._factory.fail_codegen(
                alpha_index=idx, stage="wrapper",
                error=f"{type(exc).__name__}: {exc}", code=None, t0=t0,
            )

    def _generate_code(self, factor_name: str, formula_brief: str, df_pl) -> tuple:
        """Step 3: LLM code generation (ReAct or 1-shot)."""
        llm = build_llm_client()
        code, factor_series, error, _react_meta = llm_code_react(
            factor_name, formula_brief, df_pl, llm,
            max_repair_rounds=self.config.max_repair_rounds,
            temperature=self.config.temperature,
        )
        return code, factor_series, error, "react"

    def _fail_codegen_result(self, alpha_index, stage, error, code, t0) -> dict:
        return {
            "status": "failed", "alpha_index": alpha_index,
            "stage": stage, "error": error,
            "code": code, "code_chars": len(code) if code else 0,
            "ic_mean": None, "icir": None, "ic_winrate": None,
            "elapsed_sec": time.monotonic() - t0,
        }

    def _persist_factor(self, factor_name, code, formula_brief, backtest, h5_path, alpha_index, config):
        """DEPRECATED in PR6: kept for shim backward compat. Use _persist_via_sink instead."""
        from llmwikify.reproduction.pipeline.persist import persist_code_to_yaml
        _, factor_dir = persist_code_to_yaml(
            factor_name=factor_name, code=code, formula_brief=formula_brief,
            backtest=backtest, h5_path=str(h5_path), code_chars=len(code),
            config=config, alpha_index=alpha_index,
        )
        return factor_dir

    def _save_to_duckdb(self, factor_dir, alpha_index, backtest, factor_wide, config):
        """DEPRECATED in PR6: kept for shim backward compat. Use _persist_via_sink instead."""
        from llmwikify.reproduction.persist.factor_library import save_backtest_duckdb
        run_id = f"pipeline_a_{alpha_index:03d}"
        if factor_dir:
            rel_path = str(factor_dir.relative_to(config.factors_dir))
        else:
            rel_path = f"alpha_{alpha_index:03d}"
        save_backtest_duckdb(
            factor_name=rel_path, run_id=run_id, backtest=backtest,
            factor_wide=factor_wide, factors_dir=config.factors_dir,
        )

    def _persist_via_sink(self, fr: FactorResult) -> None:
        """L2: write YAML + DuckDB via YamlDuckdbSink (PR4) — takes FactorResult.

        L2: now takes FactorResult directly (was 5 positional args + 20-line
        dict construction). The caller (run_one_factor) already has a
        FactorResult from _success_fr.
        """
        try:
            self._yaml_sink.write_one(fr)
        except Exception as exc:
            logger.warning("[sink] YamlDuckdbSink.write_one failed for %s: %s", fr.signal.id, exc)

    def _run_one_with_recording(self, idx: int) -> FactorResult:
        """Serial path: no locks, single thread.

        PR9c: delegates record step to RecordStage (was inline _record_one).
        """
        elapsed_cum: float = time.monotonic() - self.batch_t0
        logger.info("[factor] alpha-%03d: starting (elapsed: %.0fs, failures: %d)",
                    idx, elapsed_cum, self.failures)
        result = self._run_one_with_codegen(idx)
        self._record_stage.record(result, elapsed_cum)
        return result

    def _run_serial(self, to_run: list[int]) -> None:
        for idx in to_run:
            self._run_one_with_recording(idx)
            if self.failures >= self.config.max_failures:
                logger.warning("[factor] Reached max failures (%d), stopping", self.config.max_failures)
                break
            if idx < self.config.alpha_end and self.config.delay > 0 and not self.config.no_delay:
                time.sleep(self.config.delay)

    def _run_parallel(self, to_run: list[int]) -> None:
        logger.info("[factor] Using %d concurrent workers", self.config.workers)
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = {pool.submit(self._run_one_safe, idx): idx for idx in to_run}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result(timeout=self.config.timeout + 60)
                except Exception as exc:
                    logger.warning("[factor] alpha-%03d: EXCEPTION: %s: %s",
                                   idx, type(exc).__name__, str(exc)[:100])
                    self._handle_parallel_failure(idx, type(exc).__name__, str(exc))

    def _run_one_safe(self, idx: int) -> FactorResult:
        """Parallel path: lock only around RecordStage.record (not codegen).

        PR9c: delegates record step to RecordStage (was inline _record_one).
        Bug 3 fix: LLM call is OUTSIDE the lock window.
        """
        with _llm_semaphore:
            result = self._run_one_with_codegen(idx)
            elapsed_cum = time.monotonic() - self.batch_t0
            with _print_lock:
                self._record_stage.record(result, elapsed_cum)
            return result

    def _handle_parallel_failure(self, idx: int, stage: str, error: str) -> None:
        """L2: append synthetic FactorResult (not dict) with full Bug 5 fields.

        PR9a: uses self._factory.build_signal for the Signal construction.
        PR9c: uses self._failures_ref[0] for mutable int.
        """
        result: FactorResult = FactorResult(
            signal=self._factory.build_signal(idx),
            status="failed",
            stage=stage,
            error=error[:200],
            code=None,
            code_chars=0,
            backtest={},
            elapsed_sec=0.0,
        )
        self.results.append(result)
        self._failures_ref[0] += 1
        if self._single_sink is not None:
            try:
                self._single_sink.write_one(result)
            except Exception as exc:
                logger.warning(
                    "[sink] SingleJsonSink.write_one failed for %s: %s",
                    result.signal.id, exc,
                )

    def _write_summary(self) -> None:
        """L2: delegate batch summary to BatchSummarySink (PR4 + PR5).

        No more 60-line dict→FactorResult conversion — self.results
        is already list[FactorResult].
        """
        if self._summary_sink is not None:
            self._summary_sink.write_batch(self.results)
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
