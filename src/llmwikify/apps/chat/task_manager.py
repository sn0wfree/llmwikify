"""Background task manager for research engine.

Runs research engines as independent asyncio.Tasks, decoupled
from SSE connections. Events are buffered in per-session async
queues so SSE consumers can subscribe at any time.

A secondary :class:`EventBuffer` (per session) persists events
to the autoresearch database so the history survives server
restarts and SSE reconnects.

Sprint C4: the 6 base methods (``is_running`` / ``start`` /
``cancel`` / ``get_event_stream`` / ``_run_task`` /
``_on_task_done``) now live in
:mod:`llmwikify.apps.research.base.BaseResearchTaskManager`.
This module adds the DB-backed :class:`EventBuffer` by
overriding the four ``_on_*`` hooks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from llmwikify.apps.research.base import BaseResearchTaskManager

logger = logging.getLogger(__name__)


class EventBuffer:
    """Per-session in-memory event buffer with dedup + batch DB flush.

    Decouples event emission (in hot path) from DB writes (batched).
    - Dedup key: (type, message[:200]); skip if same key seen < DEDUP_WINDOW
    - Batch flush: triggered when buffer hits BATCH_SIZE
    - Explicit flush(): call on task end to persist remaining
    - close(): mark buffer as inactive (subsequent add() is no-op)
    """

    BATCH_SIZE = 20
    DEDUP_WINDOW_S = 2.0

    def __init__(self, session_id: str, db: Any) -> None:
        self.sid = session_id
        self.db = db
        self._buf: list[dict] = []
        self._last: dict[tuple, float] = {}
        self._closed = False
        self._flush_task: asyncio.Task | None = None

    def add(self, event: dict) -> None:
        """Add an event to the buffer (sync, fast path).

        - Adds timestamp + source=engine if missing
        - Skips if dedup key seen within DEDUP_WINDOW_S
        - Triggers async flush when BATCH_SIZE reached
        """
        if self._closed:
            return
        # Copy + normalize: add timestamp/source for persistence
        e = dict(event)
        e.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        e.setdefault("source", "engine")

        key = (e.get("type"), (e.get("message") or "")[:200])
        now = time.time()
        last = self._last.get(key)
        if last is not None and (now - last) < self.DEDUP_WINDOW_S:
            return  # dedup within 2s window
        self._last[key] = now

        self._buf.append(e)
        if len(self._buf) >= self.BATCH_SIZE:
            self._flush_task = asyncio.create_task(self.flush())

    async def flush(self) -> int:
        """Persist buffered events to DB. Returns count flushed."""
        if not self._buf:
            return 0
        batch, self._buf = self._buf[:], []
        try:
            self.db.append_events(self.sid, batch)
            return len(batch)
        except Exception as ex:
            logger.warning("EventBuffer flush failed for %s: %s", self.sid, ex)
            # Re-buffer for next attempt (best effort)
            self._buf[0:0] = batch
            return 0

    def close(self) -> None:
        """Mark buffer inactive. Subsequent add() is no-op."""
        self._closed = True


class ResearchTaskManager(BaseResearchTaskManager):
    """6-step-framework task manager with DB-persisted event buffer.

    Inherits the 6 base methods from
    :class:`BaseResearchTaskManager` and overrides the four
    ``_on_*`` hooks to integrate the
    :class:`EventBuffer` (created per session in
    :meth:`_on_session_start`, fed by :meth:`_on_event`,
    flushed in :meth:`_on_task_finalize`, closed + dropped
    in :meth:`_on_session_cleanup`).
    """

    def __init__(self) -> None:
        super().__init__()
        self._buffers: dict[str, EventBuffer] = {}

    def _on_session_start(self, session_id: str, engine: Any) -> None:
        """Create per-session DB-backed EventBuffer."""
        self._buffers[session_id] = EventBuffer(session_id, engine.db)

    def _on_event(self, session_id: str, event: dict) -> None:
        """Persist each event to the EventBuffer (sync, fast path)."""
        buffer = self._buffers.get(session_id)
        if buffer is not None:
            buffer.add(event)

    def _on_task_finalize(self, session_id: str) -> None:
        """Flush remaining events to DB at task end (async)."""
        buffer = self._buffers.get(session_id)
        if buffer is None:
            return
        try:
            # Note: this is called from _run_task's finally block,
            # which is already inside the event loop.
            import asyncio as _asyncio
            _asyncio.create_task(buffer.flush())
        except Exception as ex:
            logger.warning("Final EventBuffer flush dispatch failed for %s: %s",
                           session_id, ex)

    def _on_session_cleanup(self, session_id: str) -> None:
        """Close + drop the per-session EventBuffer."""
        buf = self._buffers.pop(session_id, None)
        if buf is not None:
            buf.close()


# Global singleton
_task_manager: ResearchTaskManager | None = None


def get_task_manager() -> ResearchTaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = ResearchTaskManager()
    return _task_manager
