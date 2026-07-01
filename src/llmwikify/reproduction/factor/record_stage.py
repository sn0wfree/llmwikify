"""RecordStage — atomic record step after one signal is processed.

PR9c: extracted from v2's FactorStage. Four sub-operations:
  1. **state**       — append to results list, increment failures on fail
  2. **row log**     — BatchReporter.log_row (still takes dict)
  3. **persist**     — SingleJsonSink.write_one (per-signal JSON)
  4. **outcome log** — success/failure logger message

Why a class (vs module-level functions)?
  - Bundles the 4 sub-operations with their state (single_sink, results,
    failures) into one object — a "stage" in the pipeline.
  - Makes the lifecycle explicit: ONE call to `record()` runs all 4 steps
    in the correct order. Callers can't accidentally skip a step.
  - Testable in isolation: pass in a fixture SingleJsonSink, assert
    the 4 steps were called in order.

Why a separate class (vs FactorStage method)?
  - FactorStage is the orchestrator (~1020 lines already). Extracting
    record() reduces its surface area and makes the L3 helper boundaries
    match the actual concerns: build (ResultFactory), load (SkipLoader),
    record (RecordStage), run (FactorStage).

Why mutable state via list references (not a property)?
  - `results` is a list — already mutable.
  - `failures` is an int — Python has no mutable int. We wrap in `[0]`
    and mutate via `failures[0] += 1`. The caller (FactorStage) exposes
    a read-only `failures` property that reads `self._record_stage.failures[0]`.
  - This avoids the footgun of `record()` operating on a stale copy.

Byte-equal invariant:
  - signal.id is preserved (used as filename via SingleJsonSink)
  - result.to_dict() is preserved (used by BatchReporter.log_row)
  - Order of operations is preserved: state → log_row → persist → log_outcome
  - This means a refactor cannot change the order without breaking tests.

L4-minimal invariant (PR9c scope):
  - This module does NOT touch the backtest engine. L4 is a separate
    change in v2 (inline backtest → `self._engine.run(...)`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..backtest.base import FactorResult
    from ..reporting.reporter import BatchReporter
    from ..sink.single_json import SingleJsonSink

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecordStage:
    """Atomic record step: state + log + persist + outcome for one signal.

    Composes 4 sub-operations into a single `record()` call. Holds mutable
    state via list references (results is list, failures is [int]).

    Args:
        single_sink: SingleJsonSink (per-signal JSON writer).
        results: Mutable reference to the caller's `results` list
                 (RecordStage appends to it).
        failures: Mutable [int] wrapper (Python has no mutable int).
                  Callers expose `failures` as a read-only property.
        reporter: BatchReporter class (default: from llmwikify.reproduction.reporting).
                  Uses class-level static methods (no instantiation needed).
    """

    single_sink: Any  # SingleJsonSink
    results: list = field(default_factory=list)
    failures: list = field(default_factory=lambda: [0])
    reporter: Any = None  # BatchReporter class (lazy import to avoid cycles)

    def record(self, result: FactorResult, elapsed_cum: float) -> None:
        """Atomic record: 4 sub-operations in fixed order.

        Order (L2 byte-equal):
          1. _update_state   — append to results, +1 failures on fail
          2. log_row         — BatchReporter.log_row (takes dict)
          3. _persist_one    — SingleJsonSink.write_one
          4. _log_outcome    — success/failure logger

        Persist failure is logged but does not raise (Bug: a single sink
        error must not abort the entire batch).
        """
        idx = self._idx_from_result(result)
        self._update_state(result)
        self._get_reporter().log_row(idx, result.to_dict(), elapsed_cum)
        self._persist_one(result)
        self._log_outcome(idx, result.to_dict())

    def _update_state(self, result: FactorResult) -> None:
        """Append to results, +1 failures on non-success."""
        self.results.append(result)
        if result.status != "success":
            self.failures[0] += 1

    def _persist_one(self, result: FactorResult) -> None:
        """SingleJsonSink.write_one with exception tolerance."""
        try:
            self.single_sink.write_one(result)
        except Exception as exc:
            logger.warning(
                "[record] SingleJsonSink.write_one failed for %s: %s",
                result.signal.id, exc,
            )

    def _get_reporter(self) -> Any:
        """Lazy import to avoid import cycle."""
        if self.reporter is None:
            from ..reporting.reporter import BatchReporter as _BR

            self.reporter = _BR
        return self.reporter

    @staticmethod
    def _idx_from_result(result: FactorResult) -> int:
        """Extract alpha_index (int) from FactorResult.signal.metadata.

        Looks for 'alpha_index' first, then 'index' (backward-compat alias).
        Returns 0 if neither present (shouldn't happen for in-batch results).
        """
        meta = result.signal.metadata
        if "alpha_index" in meta and isinstance(meta["alpha_index"], int):
            return meta["alpha_index"]
        if "index" in meta and isinstance(meta["index"], int):
            return meta["index"]
        return 0

    @staticmethod
    def _log_outcome(idx: int, result: dict) -> None:
        """Log success or failure message for the recorded signal.

        Backward-compat shim (PR0 test fixture). The exact message text
        is preserved from v2's pre-PR9c implementation.
        """
        if result.get("status") != "success":
            logger.warning(
                "[factor] alpha-%03d: failed (%s)",
                idx, (result.get("error", "?") or "")[:80],
            )
        else:
            logger.info(
                "[factor] alpha-%03d: success (%.1fs)",
                idx, result.get("elapsed_sec", 0),
            )
