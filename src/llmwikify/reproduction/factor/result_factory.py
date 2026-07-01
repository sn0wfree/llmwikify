"""ResultFactory — build FactorResult from various inputs.

PR9a: extracted from v2's FactorRunner / FactorStage (L2-era):
  - `_success_fr`         → `ResultFactory.success`
  - `_fail_codegen_fr`    → `ResultFactory.fail_codegen`
  - `_fail_pipeline_fr`   → `ResultFactory.fail_pipeline`
  - `_dict_to_factor_result` → `ResultFactory.from_cached_dict`
  - `_build_signal`       → `ResultFactory.build_signal`

Why a factory class (vs module-level functions)?
  - The 5 methods are tightly related (all build a FactorResult) and share
    a single piece of state: the convention `signal.id = "{idx:03d}"` for
    byte-equal output naming.
  - v2's 5 methods were static helpers on FactorRunner/FactorStage. Promoting
    them to a class:
      (a) makes the convention explicit (`build_signal` is the entry point)
      (b) groups related operations (success / fail / cached) into one place
      (c) preserves byte-equal: `signal.id` is still `f"{idx:03d}"` (101 alphas)
          and `f"{idx:03d}"` (101-convention also used by 招商/1601, all
          have numeric idx via the SignalSource convention).
  - Could in principle be a `@dataclass(slots=True)` with zero fields (just
    methods), but the class form is more discoverable (factory = verb-ish).

Byte-equal invariant:
  - `signal.id = f"{idx:03d}"` is preserved (e.g., "001" / "010" / "100")
  - `signal.metadata["alpha_index"] = idx` is preserved (for index lookup)
  - `signal.metadata["index"] = idx` is preserved (backward-compat alias)
  - `elapsed_sec` is set the same way (`time.monotonic() - t0`)
  - `code_chars` matches `len(code)` exactly (0 if code is None)

Non-goals:
  - Does NOT perform I/O (no file reads, no LLM calls)
  - Does NOT touch `self.results` list (that's RecordStage's job, PR9c)
  - Does NOT log (caller logs)
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..backtest.base import FactorResult
from ..signal_source.base import Signal

if TYPE_CHECKING:
    import polars as pl


@dataclass(slots=True)
class ResultFactory:
    """Build FactorResult from various inputs (success / fail / cached dict).

    Stateless (no `__init__` fields). All methods are pure functions of
    their arguments + the current time. Promoted to a class so the
    `build_signal` convention is the explicit entry point.
    """

    # ── 1. Signal construction ─────────────────────────────────────

    def build_signal(
        self,
        alpha_index: int,
        name: str = "",
        formula_brief: str = "",
    ) -> Signal:
        """Build a Signal object for the given alpha_index.

        Args:
            alpha_index: 1-based index used in `signal.id = f"{idx:03d}"`.
            name: Display name (defaults to `f"alpha-{idx:03d}"`).
            formula_brief: Short formula description for log lines.

        Returns:
            Signal with id = `f"{alpha_index:03d}"` (byte-equal with v1/v2).
        """
        return Signal(
            id=f"{alpha_index:03d}",
            name=name or f"alpha-{alpha_index:03d}",
            formula_brief=formula_brief,
            metadata={"alpha_index": alpha_index, "index": alpha_index},
        )

    # ── 2. Success ─────────────────────────────────────────────────

    def success(
        self,
        *,
        alpha_index: int,
        factor_name: str,
        formula_brief: str,
        code: str,
        factor_series: pl.Series,
        h5_path: Path,
        backtest: dict,
        t0: float,
    ) -> FactorResult:
        """Build a success FactorResult after a successful backtest.

        Args:
            alpha_index: 1-based signal index.
            factor_name: Human-readable factor name.
            formula_brief: Formula summary for log lines.
            code: Generated Python function source.
            factor_series: Computed factor values (polars Series).
            h5_path: Path to written factor H5 file.
            backtest: Metrics dict from `extract_full_backtest_from_ctx`
                (or `QuantNodesBacktest.run`).
            t0: `time.monotonic()` start timestamp.

        Returns:
            FactorResult with status="success", full backtest metrics.
        """
        return FactorResult(
            signal=self.build_signal(alpha_index, factor_name, formula_brief),
            status="success",
            code=code,
            code_chars=len(code),
            factor_series=factor_series,
            h5_path=h5_path,
            backtest=backtest,
            stage=None,
            error=None,
            elapsed_sec=time.monotonic() - t0,
        )

    # ── 3. Codegen failure ─────────────────────────────────────────

    def fail_codegen(
        self,
        *,
        alpha_index: int,
        stage: str,
        error: str,
        code: str | None,
        t0: float,
    ) -> FactorResult:
        """Build a failure FactorResult when LLM code generation fails.

        Args:
            alpha_index: 1-based signal index.
            stage: Pipeline stage name where the failure occurred
                (e.g., "react", "compile", "execute").
            error: Error message (truncated to first 100 chars in log).
            code: Partial code (may be None if LLM produced nothing).
            t0: `time.monotonic()` start timestamp.

        Returns:
            FactorResult with status="failed", empty backtest dict.
        """
        return FactorResult(
            signal=self.build_signal(alpha_index),
            status="failed",
            stage=stage,
            error=error,
            code=code,
            code_chars=len(code) if code else 0,
            backtest={},
            elapsed_sec=time.monotonic() - t0,
        )

    # ── 4. Pipeline failure (post-codegen) ─────────────────────────

    def fail_pipeline(
        self,
        *,
        alpha_index: int,
        code: str,
        exc: BaseException,
        t0: float,
    ) -> FactorResult:
        """Build a failure FactorResult when post-codegen pipeline fails
        (e.g., H5 write error, QuantNodes run error, metrics extract error).

        Includes the last 1500 chars of the traceback in `metadata["traceback"]`
        so debugging info is preserved alongside the FactorResult.

        Args:
            alpha_index: 1-based signal index.
            code: Generated code (may be syntactically valid but runtime-broken).
            exc: Exception that caused the failure.
            t0: `time.monotonic()` start timestamp.

        Returns:
            FactorResult with status="failed", stage="pipeline",
            traceback in metadata.
        """
        tb: str = traceback.format_exc()
        return FactorResult(
            signal=self.build_signal(alpha_index),
            status="failed",
            stage="pipeline",
            error=f"{type(exc).__name__}: {exc}",
            code=code,
            code_chars=len(code) if code else 0,
            backtest={},
            metadata={"traceback": tb[-1500:]},
            elapsed_sec=time.monotonic() - t0,
        )

    # ── 5. Cached dict → FactorResult (resume support) ─────────────

    def from_cached_dict(self, d: dict, idx: int) -> FactorResult:
        """Convert a cached single_factor_NNN.json dict to a FactorResult.

        Used by SkipLoader (PR9b) to re-hydrate FactorResult objects from
        pre-PR9 era JSON files on resume.

        Field mapping (legacy dict → FactorResult):
          - alpha_index (int)            → signal.metadata.alpha_index
          - factor_name (str)            → signal.name
          - formula_brief (str)          → signal.formula_brief
          - status (str)                 → FactorResult.status
          - code (str | None)            → FactorResult.code
          - code_chars (int)             → FactorResult.code_chars
          - h5_path (str)                → FactorResult.h5_path (Path)
          - ic_mean (float | None)       → backtest.ic_mean
          - icir (float | None)          → backtest.icir
          - ic_winrate (float | None)    → backtest.win_rate
          - stage (str | None)           → FactorResult.stage
          - error (str | None)           → FactorResult.error
          - elapsed_sec (float)          → FactorResult.elapsed_sec

        Args:
            d: Loaded dict from `single_factor_NNN.json`.
            idx: 1-based signal index (used for `signal.id`).

        Returns:
            FactorResult with `signal.id = f"{idx:03d}"` (byte-equal).
        """
        h5_str = d.get("h5_path")
        return FactorResult(
            signal=self.build_signal(
                idx,
                name=d.get("factor_name", f"alpha-{idx:03d}"),
                formula_brief=d.get("formula_brief", ""),
            ),
            status=d.get("status", "unknown"),
            code=d.get("code"),
            code_chars=d.get("code_chars", 0),
            h5_path=Path(h5_str) if h5_str else None,
            backtest={
                "ic_mean": d.get("ic_mean"),
                "icir": d.get("icir"),
                "win_rate": d.get("ic_winrate"),
            },
            stage=d.get("stage"),
            error=d.get("error"),
            elapsed_sec=d.get("elapsed_sec", 0.0),
        )
