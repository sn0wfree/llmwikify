"""Process-wide LLM metrics collector (Phase 8, Pass7, 2026-06-22).

Lightweight singleton that aggregates LLM-call metrics from
``ChatRunnerV2._stream_llm`` so the ``/api/llm/metrics`` HTTP
endpoint can return per-prompt stats.

Design notes:
  - This collector is **separate** from
    ``apps/chat/state.py:MetricsCollector`` (which is research-session
    scoped, file/markdown backed). Phase 8 keeps them independent
    because the chat side needs per-process aggregate metrics
    (across sessions), not per-session stats.
  - Records are bounded by ``max_records`` (default 1000) so the
    process doesn't grow unbounded under load.
  - Thread-safe via a single ``threading.Lock`` (chat is async but
    metrics writes happen in worker threads when LLM streams run
    in subprocess pools).
  - The collector is a **facade** (GoF Facade) over a list + lock.

Used by:
  - ``runner_v2.py:_stream_llm`` (Pass7) — wraps the call with
    ``measure_latency()`` and records latency on completion.
  - ``interfaces/server/http/routes.py`` (Pass7) — exposes a JSON
    summary via ``GET /api/llm/metrics``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

from llmwikify.foundation.utils_timing import measure_latency

logger = logging.getLogger(__name__)


class LLMMetricsCollector:
    """Process-wide LLM-call metrics (Phase 8).

    Attributes:
        max_records: Bounded buffer size (default 1000).
    """

    def __init__(self, max_records: int = 1000) -> None:
        self._records: deque[dict[str, Any]] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._total_latency_ms = 0
        self._total_chars_in = 0
        self._success_count = 0
        self._error_count = 0

    def record(
        self,
        prompt_name: str,
        latency_ms: int,
        chars_in: int = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record one LLM-call metric. Thread-safe.

        Args:
            prompt_name: Logical name (e.g. ``"chat_reason"``).
            latency_ms: Wall-clock latency.
            chars_in: Approximate input size in chars.
            success: True on success, False on exception.
            error: Stringified exception on failure, "" on success.
        """
        rec: dict[str, Any] = {
            "prompt_name": prompt_name,
            "latency_ms": latency_ms,
            "chars_in": chars_in,
            "success": success,
            "error": error,
            "recorded_at": time.time(),
        }
        with self._lock:
            self._records.append(rec)
            self._total_latency_ms += latency_ms
            self._total_chars_in += chars_in
            if success:
                self._success_count += 1
            else:
                self._error_count += 1

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary (for ``/api/llm/metrics``).

        Includes:
          - ``total_records``: number of LLM calls recorded.
          - ``success_count`` / ``error_count``: outcome tallies.
          - ``total_latency_ms`` / ``avg_latency_ms``: latency stats.
          - ``total_chars_in``: aggregate input size.
          - ``uptime_seconds``: process lifetime.
          - ``by_prompt``: per-prompt aggregates (count, avg latency,
            error count).
          - ``recent``: the most recent ``max(20, len)`` records.
        """
        with self._lock:
            records = list(self._records)
            total_latency = self._total_latency_ms
            total_chars = self._total_chars_in
            success_n = self._success_count
            error_n = self._error_count

        uptime = time.monotonic() - self._started_at
        total = len(records)
        avg = (total_latency // total) if total > 0 else 0

        # Per-prompt aggregation
        by_prompt: dict[str, dict[str, Any]] = {}
        for r in records:
            name = r["prompt_name"]
            bucket = by_prompt.setdefault(name, {
                "count": 0,
                "total_latency_ms": 0,
                "error_count": 0,
                "total_chars_in": 0,
            })
            bucket["count"] += 1
            bucket["total_latency_ms"] += r["latency_ms"]
            bucket["total_chars_in"] += r.get("chars_in", 0)
            if not r["success"]:
                bucket["error_count"] += 1
        # Add avg per bucket
        for _name, b in by_prompt.items():
            b["avg_latency_ms"] = (
                b["total_latency_ms"] // b["count"] if b["count"] > 0 else 0
            )

        recent_count = min(20, len(records))
        recent = [
            {
                k: v for k, v in r.items() if k != "recorded_at"
            }
            for r in list(records)[-recent_count:]
        ]

        return {
            "total_records": total,
            "success_count": success_n,
            "error_count": error_n,
            "total_latency_ms": total_latency,
            "avg_latency_ms": avg,
            "total_chars_in": total_chars,
            "uptime_seconds": round(uptime, 3),
            "by_prompt": by_prompt,
            "recent": recent,
        }

    def reset(self) -> None:
        """Clear all records (mainly for tests)."""
        with self._lock:
            self._records.clear()
            self._total_latency_ms = 0
            self._total_chars_in = 0
            self._success_count = 0
            self._error_count = 0
            self._started_at = time.monotonic()


# ─── Process-wide singleton ────────────────────────────────────


_singleton: LLMMetricsCollector | None = None
_singleton_lock = threading.Lock()


def get_llm_metrics_collector() -> LLMMetricsCollector:
    """Return the process-wide LLM metrics collector (singleton).

    Lazy-initialised on first call. Safe to call from multiple
    threads.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = LLMMetricsCollector()
    return _singleton


# ─── Async stream helpers (R-1) ─────────────────────────────────


async def iter_with_metrics(
    source: Callable[[], Any] | AsyncIterator[dict],
    prompt_name: str,
    chars_in: int,
) -> AsyncIterator[dict]:
    """Wrap an async-iter source with latency+metrics recording.

    ``source`` may be either:
      - a zero-arg callable returning an async iterable (preferred
        when the source itself is eagar — defers creation until
        inside the timing window); or
      - an already-built async iterable (e.g. the result of calling
        ``llm.astream_chat(...)`` directly).

    On exit (success, exhaustion, or exception) one ``LLMCallMetrics``
    entry is recorded via the process-wide collector. Any exception is
    re-raised after recording ``success=False``.

    Args:
        source: Async-iter factory or pre-built async iterable.
        prompt_name: Logical name (e.g. ``"chat_reason"``).
        chars_in: Approximate input size in chars for the call.

    Yields:
        The events produced by the source iterable, unchanged.
    """
    success_flag = True
    error_str = ""
    with measure_latency() as get_ms:
        try:
            if callable(source) and not hasattr(source, "__aiter__"):
                iterable = source()
            else:
                iterable = source
            async for ev in iterable:
                yield ev
        except Exception as exc:
            success_flag = False
            error_str = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            get_llm_metrics_collector().record(
                prompt_name=prompt_name,
                latency_ms=get_ms(),
                chars_in=chars_in,
                success=success_flag,
                error=error_str,
            )


async def call_with_metrics(
    call_factory: Callable[[], Any],
    prompt_name: str,
    chars_in: int,
) -> AsyncIterator[dict]:
    """Wrap a sync single-shot LLM call with latency+metrics + DONE event.

    Calls ``call_factory()`` once, wraps the result in a single
    ``{"type": "done", "content": ...}`` event (using
    ``getattr(reply, "content", "") or ""`` for safety). Records a
    single metrics entry on exit. Re-raises any exception after
    recording ``success=False``.

    Args:
        call_factory: Zero-arg callable invoking the LLM
            (e.g. ``lambda: llm.chat(messages, tools=tools)``).
        prompt_name: Logical name (e.g. ``"chat_fallback"``).
        chars_in: Approximate input size in chars for the call.

    Yields:
        Exactly one ``{"type": "done", "content": str}`` event.
    """
    # Imported here to avoid a top-level circular import (events.py
    # is a leaf module; llm_metrics.py is also leaf, but we keep the
    # import local as documentation of the dependency direction).
    from llmwikify.apps.chat.agent.events import DONE

    success_flag = True
    error_str = ""
    with measure_latency() as get_ms:
        try:
            reply = call_factory()
            yield {
                "type": DONE,
                "content": getattr(reply, "content", "") or "",
            }
        except Exception as exc:
            success_flag = False
            error_str = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            get_llm_metrics_collector().record(
                prompt_name=prompt_name,
                latency_ms=get_ms(),
                chars_in=chars_in,
                success=success_flag,
                error=error_str,
            )


__all__ = [
    "LLMMetricsCollector",
    "call_with_metrics",
    "get_llm_metrics_collector",
    "iter_with_metrics",
]
