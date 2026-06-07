"""Background task manager for research engine.

Runs research engines as independent asyncio.Tasks, decoupled from SSE connections.
Events are buffered in per-session async queues so SSE consumers can subscribe at any time.

A secondary EventBuffer (per session) persists events to the autoresearch
database so the history survives server restarts and SSE reconnects.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from llmwikify.apps.chat.engine import ResearchEngine

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
            return  # 2s 内同 type+message 视为重复
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


class ResearchTaskManager:
    """Manages background research tasks, one per session."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}
        self._engines: dict[str, ResearchEngine] = {}
        self._buffers: dict[str, EventBuffer] = {}

    def is_running(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return task is not None and not task.done()

    def start(
        self,
        session_id: str,
        query: str,
        engine: ResearchEngine,
        resume: bool = False,
    ) -> None:
        """Start a research task in the background."""
        if self.is_running(session_id):
            logger.warning("Task %s already running, skipping", session_id)
            return

        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._queues[session_id] = queue
        self._engines[session_id] = engine
        # Persistence buffer (DB-backed, survives server restart)
        self._buffers[session_id] = EventBuffer(session_id, engine.db)

        task = asyncio.create_task(
            self._run_task(session_id, query, engine, queue, resume),
            name=f"research-{session_id}",
        )
        self._tasks[session_id] = task
        task.add_done_callback(lambda t, sid=session_id: self._on_task_done(sid, t))
        logger.info("Started research task %s (resume=%s)", session_id, resume)

    def cancel(self, session_id: str) -> bool:
        """Cancel a running task."""
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled research task %s", session_id)
            return True
        return False

    async def get_event_stream(self, session_id: str) -> AsyncIterator[dict]:
        """Get an async iterator of events for a session.

        Yields events from the per-session queue. Returns when the task
        completes and all events are consumed.
        """
        queue = self._queues.get(session_id)
        if queue is None:
            return

        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                # Check if task is still running
                task = self._tasks.get(session_id)
                if task is None or task.done():
                    break
                # Wait a bit for new events
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

            if event is None:
                # Sentinel: task completed
                break
            yield event

    async def _run_task(
        self,
        session_id: str,
        query: str,
        engine: ResearchEngine,
        queue: asyncio.Queue[dict | None],
        resume: bool,
    ) -> None:
        """Run the engine in background, feeding events to the queue
        AND persisting to DB via EventBuffer.
        """
        buffer = self._buffers.get(session_id)
        try:
            async for event in engine.run(session_id, query, resume=resume):
                await queue.put(event)
                if buffer is not None:
                    buffer.add(event)
        except asyncio.CancelledError:
            logger.info("Research task %s cancelled", session_id)
            # Mark as paused in DB so user can resume
            try:
                db = engine.db
                session = db.get_research_session(session_id)
                if session and session.get("status") not in ("done", "cancelled", "paused", "timeout", "error"):
                    db.update_research_status(session_id, "paused", session.get("current_step"))
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error("Research task %s failed: %s", session_id, e, exc_info=True)
            err_event = {"type": "error", "error": str(e)}
            await queue.put(err_event)
            if buffer is not None:
                buffer.add(err_event)
        finally:
            # Sentinel to signal completion
            await queue.put(None)
            # Flush remaining events to DB
            if buffer is not None:
                try:
                    await buffer.flush()
                except Exception as ex:
                    logger.warning("Final EventBuffer flush failed for %s: %s",
                                   session_id, ex)

    def _on_task_done(self, session_id: str, task: asyncio.Task) -> None:
        """Clean up after a task completes."""
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("Research task %s finished with error: %s", session_id, exc)
        else:
            logger.info("Research task %s finished", session_id)

        self._tasks.pop(session_id, None)
        # Keep queue for late subscribers to drain
        # Close + remove the persistence buffer (events already flushed)
        buf = self._buffers.pop(session_id, None)
        if buf is not None:
            buf.close()
        # Clean up engine reference
        self._engines.pop(session_id, None)


# Global singleton
_task_manager: ResearchTaskManager | None = None


def get_task_manager() -> ResearchTaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = ResearchTaskManager()
    return _task_manager
