"""FactorResult dataclass + BacktestEngine Protocol.

FactorResult is the per-signal output of `PaperPipeline._process_one_signal`.
It carries:
  - `signal`: the source Signal (from SignalSource, PR2)
  - `code` / `code_chars` / `factor_series`: codegen output
  - `backtest`: metrics dict from BacktestEngine.run()
  - `status` / `stage` / `error`: success/failure accounting
  - `elapsed_sec`: wall-clock time for this signal

BacktestEngine is a Protocol — any class with `run(code, h5_path, signal) -> dict`
matches. This lets users plug in:
  - QuantNodesBacktest (production, PR3)
  - StubBacktest (testing)
  - CloudBacktest (future)
  - SimpleCrossSectionBacktest (no engine, just stats)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import polars as pl

    from ..signal_source.base import Signal


@dataclass(slots=True)
class FactorResult:
    """Result of processing one Signal through the pipeline.

    Attributes:
        signal: The source Signal (from SignalSource).
        status: "success" or "failed".
        code: Generated Python code (None on codegen failure).
        code_chars: Length of code (0 if no code).
        factor_series: Computed factor series (None if failed before execute).
        h5_path: Path to factor H5 file (None if H5 write skipped).
        backtest: Metrics dict from BacktestEngine.run() (empty on failure).
        stage: Where failure occurred (None on success).
        error: Error message (None on success).
        elapsed_sec: Wall-clock time for this signal.
        metadata: Free-form extra info (LLM iterations, stop_reason, etc.).
    """

    signal: Signal
    status: str
    code: str | None = None
    code_chars: int = 0
    factor_series: pl.Series | None = None
    h5_path: Path | None = None
    backtest: dict[str, Any] = field(default_factory=dict)
    stage: str | None = None
    error: str | None = None
    elapsed_sec: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (mirrors v2 result dict).

        Used by SingleJsonSink (PR4) to write single_factor_NNN.json.
        """
        alpha_idx = self._legacy_alpha_index()
        out: dict[str, Any] = {
            "status": self.status,
            "stage": self.stage,
            "error": self.error,
            "code": self.code,
            "code_chars": self.code_chars,
            "factor_series_len": len(self.factor_series) if self.factor_series is not None else 0,
            "factor_series_dtype": str(self.factor_series.dtype) if self.factor_series is not None else None,
            "h5_path": str(self.h5_path) if self.h5_path else None,
            "ic_mean": self.backtest.get("ic_mean"),
            "icir": self.backtest.get("icir"),
            "ic_winrate": self.backtest.get("win_rate"),
            "elapsed_sec": self.elapsed_sec,
        }
        if alpha_idx is not None:
            out["alpha_index"] = alpha_idx
        return out

    def _legacy_alpha_index(self) -> int | None:
        """Extract alpha_index from signal metadata for v2 compat."""
        meta: dict = self.signal.metadata
        if "alpha_index" in meta and isinstance(meta["alpha_index"], int):
            return meta["alpha_index"]
        if "index" in meta and isinstance(meta["index"], int):
            return meta["index"]
        return None


class BacktestEngine(Protocol):
    """Runs generated code against market data and returns metrics dict.

    Implementations may be synchronous (QuantNodesBacktest) or async.
    Returned dict shape (convention):
      {
        "ic_mean": float | None,
        "icir": float | None,
        "win_rate": float | None,
        # ...other engine-specific metrics
      }
    """

    def run(
        self,
        code: str,
        h5_path: Path,
        signal: Signal,
    ) -> dict[str, Any]: ...
