"""The per-step state trace of the chat agent loop.

Moved out of ``runner_v2.py`` so the chat *plan* can use it without a
circular import (the plan lives next to the runner). The old private
names stay importable from ``runner_v2`` as aliases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class StateTraceEntry:
    """Single state transition in the 5-step machine.

    Pattern borrowed from nanobot v0.2.1 ``StateTraceEntry``
    (``nanobot/agent/loop.py``) but trimmed to our 5 steps.
    """

    state: str
    started_at: float
    duration_ms: float
    event: str  # "ok" | "error" | "skipped"
    error: str | None = None


class StateTrace:
    """Context manager that records a state transition.

    Records ``{state, started_at, duration_ms, event, error}`` to
    ``ctx.state_trace``.  Pattern from nanobot v0.2.1
    ``StateTraceEntry`` — but ours is a context manager so the
    per-step wrapper stays a single line::

        with StateTrace(ctx, "REASON") as tr:
            ...
    """

    __slots__ = ("_ctx", "state", "_start", "event", "error")

    def __init__(self, ctx: Any, state: str) -> None:
        self._ctx = ctx
        self.state = state
        self._start = 0.0
        self.event = "ok"
        self.error: str | None = None

    def __enter__(self) -> StateTrace:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = (time.monotonic() - self._start) * 1000.0
        if exc is not None:
            self.event = "error"
            self.error = f"{type(exc).__name__}: {exc}"
        self._ctx.state_trace.append(
            StateTraceEntry(
                state=self.state,
                started_at=self._start,
                duration_ms=duration_ms,
                event=self.event,
                error=self.error,
            )
        )
        return False  # do not suppress exception


__all__ = ["StateTrace", "StateTraceEntry"]
