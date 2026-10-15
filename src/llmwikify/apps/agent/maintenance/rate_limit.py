"""Sliding-window rate limiter for background LLM calls.

Keeps maintenance work (auto-ingest backlog replay, gap-filler lint)
from saturating the shared LLM provider and starving the foreground
chat/research traffic: by default at most **5 LLM-processing units may
start within any 5s window** (config: ``maintenance.llm_rate_limit``).

Unit semantics (one ``acquire()``):
- Track A auto-ingest: one ``wiki._llm_process_source()`` chain
  (internally 2-4 API calls: section-select → analyze → ops).
- Track B gap-filler: one ``wiki.lint()`` (internally 1 gap-detect call).

The limiter is process-wide (one instance on MaintenanceManager shared
by all wikis) so the budget is global, not per-wiki. It complements —
not replaces — the ``asyncio.Semaphore(3)`` concurrency cap.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any


class SlidingWindowRateLimiter:
    """Async sliding-window limiter with FIFO fairness.

    ``acquire()`` returns as soon as a slot in the current window is
    free. Waiters sleep while holding the lock on purpose: earlier
    waiters re-check first when the window slides open (no thundering
    herd, strict FIFO).
    """

    def __init__(
        self,
        max_requests: int = 5,
        window_seconds: float = 5.0,
        enabled: bool = True,
        name: str = "llm",
    ) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(0.01, float(window_seconds))
        self.enabled = enabled
        self.name = name
        self._events: deque[float] = deque()
        self._lock: asyncio.Lock | None = None  # lazy: bind to running loop
        self._throttled = 0

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> bool:
        """Block until a window slot is free. Always True (keeps call
        sites simple); cancellation propagates to the caller."""
        if not self.enabled:
            return True
        async with self.lock:
            while True:
                now = time.monotonic()
                while self._events and self._events[0] <= now - self.window_seconds:
                    self._events.popleft()
                if len(self._events) < self.max_requests:
                    self._events.append(now)
                    return True
                self._throttled += 1
                wait = self._events[0] + self.window_seconds - now
                await asyncio.sleep(max(0.0, wait))

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "throttled_total": self._throttled,
            "window_in_use": len(self._events) if self.enabled else 0,
        }
