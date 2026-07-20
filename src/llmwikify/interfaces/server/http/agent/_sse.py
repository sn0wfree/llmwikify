"""SSE 流基础设施。

提供 _sse_stream 函数和 SSE 相关常量。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from llmwikify.apps.chat.bus.adapter import BusAdapter

# ─── SSE 常量 ──────────────────────────────────────────────────

# HEARTBEAT_INTERVAL: seconds between keepalive pings (15s).
# STREAM_TIMEOUT: total stream lifetime in seconds (300s = 5min).
# STUDY_STREAM_TIMEOUT: extended timeout for /study research triggers
# (30min) so long-running research workflows aren't cut off mid-run.
HEARTBEAT_INTERVAL = 15
STREAM_TIMEOUT = 300
STUDY_STREAM_TIMEOUT = 30 * 60  # 30 minutes

# /study trigger prefix (matches autoresearch_compound_skill triggers)
_STUDY_TRIGGER = "/study"


# ─── SSE 流 ────────────────────────────────────────────────────

async def _sse_stream(
    source: AsyncIterator[dict],
    *,
    session_id: str = "",
    timeout: int = STREAM_TIMEOUT,
) -> AsyncIterator[dict[str, str]]:
    """Unified SSE event stream: bus mirror + timeout + end-of-stream heartbeat.

    Args:
        source: Async iterator yielding business events (any JSON-serializable dict).
        session_id: Chat session ID for constructing the bus session_key
            (``http:{session_id}`` when present, empty string otherwise).
        timeout: Total stream lifetime in seconds. Caller may pass
            ``STUDY_STREAM_TIMEOUT`` for /study research triggers.

    Yields:
        SSE-protocol events:
          - business: ``{"event": "message", "data": json.dumps(event)}``
          - timeout: ``{"event": "message", "data": json.dumps({type: timeout, ...})}``
          - end heartbeat: ``{"event": "heartbeat", "data": ""}`` (when stream > 15s)

    Side effects:
        Each business event is mirrored to ``MessageBus`` for fan-out
        (WebSocket subscribers, future channels).
    """
    bus_adapter = BusAdapter()
    start_time = time.monotonic()
    session_key = f"http:{session_id}" if session_id else ""

    async for event in source:
        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            timeout_event = {
                "type": "timeout",
                "message": f"Stream timed out after {int(timeout // 60)} minutes",
            }
            bus_adapter.mirror_sse_event(
                timeout_event, target_id="", session_key=session_key,
            )
            yield {"event": "message", "data": json.dumps(timeout_event)}
            return
        bus_adapter.mirror_sse_event(
            event, target_id="", session_key=session_key,
        )
        yield {"event": "message", "data": json.dumps(event)}

    # End-of-stream heartbeat (unified: both /chat and /approve-and-continue).
    elapsed = time.monotonic() - start_time
    if elapsed > HEARTBEAT_INTERVAL:
        yield {"event": "heartbeat", "data": ""}
