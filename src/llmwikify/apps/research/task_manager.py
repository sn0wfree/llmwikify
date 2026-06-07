"""Background task manager for research engine.

Runs research engines as independent asyncio.Tasks, decoupled from SSE connections.
Events are buffered in per-session async queues so SSE consumers can subscribe at any time.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from .engine import ResearchEngine

logger = logging.getLogger(__name__)


class ResearchTaskManager:
    """Manages background research tasks, one per session."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}
        self._engines: dict[str, ResearchEngine] = {}

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
        """Run the engine in background, feeding events to the queue."""
        try:
            async for event in engine.run(session_id, query, resume=resume):
                await queue.put(event)
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
            await queue.put({"type": "error", "error": str(e)})
        finally:
            # Sentinel to signal completion
            await queue.put(None)

    def _on_task_done(self, session_id: str, task: asyncio.Task) -> None:
        """Clean up after a task completes."""
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("Research task %s finished with error: %s", session_id, exc)
        else:
            logger.info("Research task %s finished", session_id)

        self._tasks.pop(session_id, None)
        # Keep queue for late subscribers to drain
        # Clean up engine reference
        self._engines.pop(session_id, None)


# Global singleton
_task_manager: ResearchTaskManager | None = None


def get_task_manager() -> ResearchTaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = ResearchTaskManager()
    return _task_manager
