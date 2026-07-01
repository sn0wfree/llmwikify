"""PaperRecipe — composition root for one paper reproduction run.

A PaperRecipe declares:
  - which paper (`paper_id`, optional `paper_path`)
  - where signals come from (`signal_source` — defined in PR2)
  - where market data comes from (`data_source` — already in data_source/)
  - which backtest engine runs them (`backtest_engine` — defined in PR3)
  - where results are written (`sinks` — defined in PR4)
  - how to log progress (`reporter` — defined in PR5)
  - concurrency / delay / timeout knobs

Plug-in points are typed as Protocols (structural typing), so concrete
implementations do not need to inherit from a base class — they just need
to expose the expected methods.

PR1 scope: only the dataclass + Protocols. Concrete implementations arrive in
PR2 (SignalSource), PR3 (BacktestEngine), PR4 (Sink), PR5 (reporter).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import polars as pl

    from ..backtest.base import BacktestEngine
    from ..data_source.router import DataSource
    from ..reporting.reporter import BatchReporter
    from ..signal_source.base import Signal, SignalSource
    from ..sink.base import Sink


class _HasIterSignals(Protocol):
    """Structural type for SignalSource — used by PaperRecipe before PR2."""

    def iter_signals(self) -> Iterable[Signal]: ...


class _BacktestRunner(Protocol):
    """Structural type for BacktestEngine — used by PaperRecipe before PR3."""

    def run(self, code: str, h5_path: Path, signal: Signal) -> dict[str, Any]: ...


class _DataFetcher(Protocol):
    """Structural type for DataSource — already exists in data_source/router."""

    name: str

    def get(self, symbol: str, start: str, end: str) -> Any: ...


class _SinkWriter(Protocol):
    """Structural type for Sink — used by PaperRecipe before PR4."""

    def write_one(self, result: Any) -> Path: ...


@dataclass(slots=True)
class PaperRecipe:
    """Composition root for one paper reproduction run.

    All plug-in fields are typed as Protocols so that concrete implementations
    in PR2-PR5 need not inherit from a base class. Pass any object that
    structurally matches the expected interface.

    Attributes:
        paper_id: Unique paper identifier (used for output paths, logs).
        paper_path: Optional path to source PDF / MD / URL (for paper_understanding stage).
        signal_source: Iterable of `Signal` objects (formulas extracted from paper).
        data_source: OHLCV data fetcher.
        backtest_engine: Runs code against data, returns metrics dict.
        sinks: One or more output writers (YAML, DuckDB, JSON, etc.).
        reporter: Logger facade for batch progress / summary.
        delay: Seconds to sleep between signals in serial mode (default 3.0).
        workers: Concurrent worker count (max 3 for LLM rate limits).
        timeout: Per-signal timeout in seconds.
        skip_existing: If True, skip signals whose `id` already has a result file.
        max_failures: Stop the batch after N consecutive failures.
        metadata: Free-form dict passed through to all stages.
    """

    paper_id: str
    signal_source: _HasIterSignals
    data_source: _DataFetcher
    backtest_engine: _BacktestRunner
    sinks: list[_SinkWriter] = field(default_factory=list)
    reporter: Any = None  # BatchReporter (PR5); Any to avoid hard dep on PR5
    paper_path: Path | None = None
    delay: float = 3.0
    workers: int = 1
    timeout: int = 180
    skip_existing: bool = False
    max_failures: int = 999
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paper_id:
            raise ValueError("paper_id must be non-empty")
        if self.workers < 1:
            raise ValueError(f"workers must be >= 1, got {self.workers}")
        if self.workers > 3:
            import warnings
            warnings.warn(
                f"workers={self.workers} exceeds LLM rate-limit cap (3). "
                f"PaperPipeline will cap to 3.",
                stacklevel=2,
            )
            self.workers = 3
