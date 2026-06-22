"""Telemetry counter for LLM compile loop (PR-7, 2026-06-21).

Lightweight in-process metrics for compile/extract success/failure rates.
Useful for monitoring Loop v4 performance without external dependencies.

Usage:
    from .telemetry import get_telemetry
    t = get_telemetry()
    t.record("compile.success", factor_name="momentum_20")
    t.record("compile.failure", error_kind="MissingKwarg")
    print(t.summary())
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class Telemetry:
    """Thread-safe in-process metric collector.

    Tracks event counts and recent events (last 100) for debugging.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._recent: list[dict[str, Any]] = []
        self._recent_max = 100

    def record(self, event: str, **kwargs: Any) -> None:
        """Record an event with optional context."""
        with self._lock:
            self._counts[event] += 1
            entry = {"event": event, **kwargs}
            self._recent.append(entry)
            if len(self._recent) > self._recent_max:
                self._recent = self._recent[-self._recent_max:]

    def count(self, event: str) -> int:
        """Get count for a specific event."""
        with self._lock:
            return self._counts.get(event, 0)

    def summary(self) -> dict[str, Any]:
        """Return snapshot of all counts."""
        with self._lock:
            return {
                "counts": dict(self._counts),
                "total_events": sum(self._counts.values()),
                "recent": list(self._recent[-10:]),
            }

    def reset(self) -> None:
        """Clear all metrics."""
        with self._lock:
            self._counts.clear()
            self._recent.clear()


# Singleton
_INSTANCE: Telemetry | None = None
_INSTANCE_LOCK = threading.Lock()


def get_telemetry() -> Telemetry:
    """Get the singleton Telemetry instance."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = Telemetry()
    return _INSTANCE


__all__ = ["Telemetry", "get_telemetry"]
