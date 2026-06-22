"""Latency measurement context manager (Pass5, 2026-06-22).

Decorator-pattern CM that yields an integer ``duration_ms`` after the
block. Used to fill the ``duration_ms`` field of tool_call_end /
tool_call_error SSE events (currently emitted as 0 by
``runner_v2.py``).

Usage::

    from llmwikify.foundation.utils.timing import measure_latency

    with measure_latency() as get_ms:
        result = await some_tool(args)

    yield {
        "type": events.TOOL_CALL_END,
        "tool": tool_name,
        "duration_ms": get_ms(),
        ...
    }

The CM is deliberately tiny (one function, ~25 LOC) so it can be
imported by both ``runner_v2.py`` and any future module that wants
end-to-end latency for an async block. Mirrors nanobot's
``time.monotonic() - start`` pattern but as a reusable CM instead
of inline timing.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def measure_latency() -> Iterator:
    """Yield a callable that returns the elapsed milliseconds.

    The yielded ``get_ms`` returns the elapsed ms at the time of
    the call. Multiple calls after the CM exits return the same
    cached value (taken at CM exit time). Calling before the CM
    exits returns the live elapsed time (uncommon usage).

    Returns:
        ``get_ms() -> int`` — call AFTER the CM block to get elapsed ms.
    """
    start = time.monotonic()
    cached_ms: list[int | None] = [None]

    def get_ms() -> int:
        if cached_ms[0] is not None:
            return cached_ms[0]
        return int((time.monotonic() - start) * 1000.0)

    try:
        yield get_ms
    finally:
        # Cache final timing so post-exit callers get a stable value.
        cached_ms[0] = int((time.monotonic() - start) * 1000.0)


__all__ = ["measure_latency"]
