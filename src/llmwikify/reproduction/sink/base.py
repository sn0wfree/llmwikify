"""Sink Protocol — output destination for FactorResult.

A Sink writes one FactorResult to some destination (file, DB, webhook, MQ, etc.).
Three methods:
  - write_one(result) → Path: per-signal write (called in pipeline loop)
  - write_batch(results) → list[Path]: end-of-batch aggregation (called once
    after all signals processed). Default impl returns [].
  - flush() → None: close/cleanup. Default impl is no-op.

Why a Sink Protocol (not ABC)?
  - Different sinks have wildly different interfaces (file vs webhook)
  - Structural typing lets duck-typed classes satisfy it without inheritance
  - PR4 provides 3 file-based sinks; future PRs can add webhook/MQ sinks
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..backtest.base import FactorResult


class Sink(Protocol):
    """Output destination for FactorResult (file, DB, webhook, ...)."""

    def write_one(self, result: FactorResult) -> Path:
        """Write one FactorResult to the destination.

        Returns:
            Path to the written artifact (file path, message id, etc.).
            On error, may return a sentinel like Path("/dev/null") or raise.
        """
        ...

    def write_batch(self, results: list[FactorResult]) -> list[Path]:
        """End-of-batch aggregation (e.g. summary JSON/MD).

        Called once after all signals processed. Default returns [].
        """
        return []

    def flush(self) -> None:
        """Cleanup resources (close files, flush buffers). No-op default."""
        return None
