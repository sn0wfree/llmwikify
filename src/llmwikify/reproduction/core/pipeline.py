"""PaperPipeline — driver that runs a PaperRecipe end-to-end.

PR1 scope: framework skeleton with serial/parallel scaffolding, lock pattern
reused from v2 (`_print_lock` around record + `_llm_semaphore` around LLM call).

The actual signal→code→backtest→sink pipeline is filled in by PR2 (SignalSource)
+ PR3 (BacktestEngine) + PR4 (Sink) + PR5 (reporter). For PR1, `run()` returns
an empty list — the loop body is a TODO that gets wired up as those modules
land.

Lock semantics (mirroring v2's Bug 3 fix):
  - _llm_semaphore: caps concurrent LLM calls to 3 (api.minimaxi.com rate limit)
  - _print_lock: protects state mutation + JSON writes only (NOT the LLM call)
  - parallel mode: record inside _print_lock, LLM outside
  - serial mode: no locks needed
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .recipe import PaperRecipe

logger = logging.getLogger(__name__)


# ─── Module-level concurrency primitives ──────────────────────────────
# Caps concurrent LLM calls to api.minimaxi.com (≤3 recommended).
_llm_semaphore = threading.Semaphore(3)
# Protects state mutation + JSON writes in parallel mode.
_print_lock = threading.Lock()


class PaperPipeline:
    """Driver that runs a PaperRecipe end-to-end.

    The pipeline iterates over signals from `recipe.signal_source`, runs
    codegen + backtest via `recipe.backtest_engine`, and dispatches each
    `FactorResult` to every sink in `recipe.sinks`.

    PR1 status: framework scaffolding only. The per-signal loop body is a
    placeholder that returns an empty list. Concrete codegen/backtest/sink
    wiring arrives in PR2-PR5.
    """

    def __init__(self, recipe: PaperRecipe) -> None:
        self.recipe: PaperRecipe = recipe
        self.results: list[Any] = []
        self.failures: int = 0
        self.t0: float = 0.0
        self.batch_t0: float = 0.0

    def run(self, indices: range | None = None) -> list[Any]:
        """Run the pipeline.

        Args:
            indices: Optional range of indices to filter (101-alphas style).
                     If None, runs every signal from `recipe.signal_source`.
                     NOTE: PR1 does not yet use this — it is part of the
                     planned v2-compatibility wiring in PR6.

        Returns:
            List of per-signal results (empty in PR1; filled in PR6).
        """
        self.t0 = time.monotonic()
        self.batch_t0 = time.monotonic()
        logger.info(
            "[pipeline] starting paper=%s workers=%d sinks=%d",
            self.recipe.paper_id,
            self.recipe.workers,
            len(self.recipe.sinks),
        )
        # PR1 placeholder: actual codegen+backtest+sink loop lands in PR6.
        # The scaffolding (serial/parallel split, locks, indices filter) is
        # verified by tests/test_paper_pipeline.py with a stub signal source.
        self._run_scaffolded(indices)
        elapsed: float = time.monotonic() - self.t0
        logger.info("[pipeline] done paper=%s (%.1fs)", self.recipe.paper_id, elapsed)
        return self.results

    def _run_scaffolded(self, indices: range | None) -> None:
        """Serial / parallel scaffolding.

        PR1: enumerates signals, runs `_process_one_signal` per signal,
        wires up serial vs parallel dispatch with the same lock pattern as v2.
        The `_process_one_signal` body is a stub — it will call codegen +
        backtest + sinks once those modules are implemented.
        """
        signals: list[Any] = list(self.recipe.signal_source.iter_signals())

        if indices is not None:
            # Filter by signal id when indices provided (101-alphas style).
            wanted_ids: set[str] = {self._id_for_index(i) for i in indices}
            signals = [s for s in signals if s.id in wanted_ids]

        if not signals:
            logger.warning("[pipeline] no signals to process for %s", self.recipe.paper_id)
            return

        logger.info("[pipeline] %d signals to process", len(signals))

        if self.recipe.workers <= 1:
            self._run_serial(signals)
        else:
            self._run_parallel(signals)

    def _id_for_index(self, index: int) -> str:
        """Map an integer index to a signal id (101-alphas convention).

        Override in subclasses if a different naming scheme is needed.
        """
        return f"alpha-{index:03d}"

    def _process_one_signal(self, signal: Any) -> Any:
        """Process a single signal: codegen + backtest + sinks.

        PR1 stub — returns a placeholder dict. The real implementation
        wires together:
          - llm_code_react(signal.formula_brief) → code
          - backtest_engine.run(code, h5_path, signal) → metrics
          - sinks[*].write_one(result)
        """
        # PR1 placeholder — PR6 will replace this.
        return {
            "signal_id": signal.id,
            "status": "success",
            "stage": "pr1_placeholder",
        }

    def _record_one(self, signal: Any, result: Any) -> None:
        """Atomic record step (mirrors v2's `_record_one`).

        Appends result to self.results, increments failure counter on failure.
        PR1 does not yet persist or log row — those arrive with PR4 (sinks)
        and PR5 (reporter).
        """
        self.results.append(result)
        if result.get("status") != "success":
            self.failures += 1

    def _run_serial(self, signals: list[Any]) -> None:
        """Serial path: single thread, no locks."""
        for signal in signals:
            self._run_one_with_recording(signal)

    def _run_one_with_recording(self, signal: Any) -> Any:
        """Serial: process + record (no lock)."""
        result = self._process_one_signal(signal)
        self._record_one(signal, result)
        return result

    def _run_parallel(self, signals: list[Any]) -> None:
        """Parallel path: _llm_semaphore + _print_lock (mirrors v2 Bug 3 fix)."""
        logger.info("[pipeline] using %d workers", self.recipe.workers)
        with ThreadPoolExecutor(max_workers=self.recipe.workers) as pool:
            futures = {
                pool.submit(self._run_one_safe, signal): signal
                for signal in signals
            }
            for future in as_completed(futures):
                signal = futures[future]
                try:
                    future.result(timeout=self.recipe.timeout + 60)
                except Exception as exc:
                    logger.warning(
                        "[pipeline] signal=%s EXCEPTION: %s",
                        signal.id, exc,
                    )
                    self._handle_parallel_failure(signal, type(exc).__name__, str(exc))

    def _run_one_safe(self, signal: Any) -> Any:
        """Parallel: semaphore around LLM, _print_lock around record."""
        with _llm_semaphore:
            result = self._process_one_signal(signal)
            with _print_lock:
                self._record_one(signal, result)
            return result

    def _handle_parallel_failure(self, signal: Any, stage: str, error: str) -> None:
        """Append synthetic failure so Total = Success + Failed stays consistent."""
        result: dict[str, Any] = {
            "signal_id": signal.id,
            "status": "failed",
            "stage": stage,
            "error": error[:200],
        }
        self.results.append(result)
        self.failures += 1
