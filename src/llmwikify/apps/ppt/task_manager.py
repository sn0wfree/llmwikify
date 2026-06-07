"""Background task manager for PPT generation.

Runs PPT generation as independent asyncio.Tasks, decoupled from SSE connections.
Events are buffered in per-task async queues so SSE consumers can subscribe at any time.

v0.5: All task state mirrored to ppt_tasks table in AgentDatabase for persistence
across page refreshes and server restarts. asyncio.Task instances remain in-memory
because they cannot be serialized.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class PPTTaskManager:
    """Manages background PPT generation tasks.

    State model (v0.5):
    - asyncio.Task + per-task queue: in-memory only (cannot serialize)
    - Status / result / error: mirrored to ppt_tasks table in AgentDatabase
    - get_status() / get_task(): read from DB (covers past tasks after restart)
    - get_event_stream(): reads from in-memory queue (live events only)
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}

    def create_task(
        self,
        generate_fn: Any,
        title: str,
        theme: str,
        source_type: str | None,
        source_id: str | None,
        outline: Any,
        language: str = "zh",
        slide_count: int = 0,
    ) -> str:
        """Create a new background PPT generation task. Returns task_id.

        The DB row is created up-front (status='pending'). The asyncio.Task
        then drives the actual generation and updates the row's status.
        """
        import json as _json
        outline_json = _json.dumps(
            outline.model_dump() if hasattr(outline, "model_dump") else outline,
            ensure_ascii=False,
        )
        task_id = self.db.create_ppt_task(
            title=title,
            theme=theme,
            source_type=source_type,
            source_id=source_id,
            outline_json=outline_json,
            slide_count=slide_count,
        )
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._queues[task_id] = queue

        task = asyncio.create_task(
            self._run_task(task_id, generate_fn, outline, theme, language,
                           source_type, source_id, queue),
            name=f"ppt-{task_id}",
        )
        self._tasks[task_id] = task
        task.add_done_callback(lambda t, tid=task_id: self._on_task_done(tid, t))
        logger.info("Created PPT task %s (title=%r)", task_id, title)
        return task_id

    def get_status(self, task_id: str) -> dict[str, Any]:
        """Get current task status. Reads from DB for persistence."""
        row = self.db.get_ppt_task(task_id)
        if row is None:
            return {"task_id": task_id, "status": TaskStatus.ERROR.value,
                    "error": "Task not found"}
        result: dict[str, Any] = {
            "task_id": task_id,
            "status": row["status"],
        }
        if "presentation" in row and row["presentation"]:
            result["presentation"] = row["presentation"]
        if row.get("error"):
            result["error"] = row["error"]
        return result

    async def get_event_stream(self, task_id: str) -> AsyncIterator[dict]:
        """Get an async iterator of events for a task.

        Reads from the in-memory queue. Returns when the task completes
        and all events are consumed. Late subscribers (e.g. after server
        restart) get an empty stream — they should call get_status() instead.
        """
        queue = self._queues.get(task_id)
        if queue is None:
            return

        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                task = self._tasks.get(task_id)
                if task is None or task.done():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

            if event is None:
                break
            yield event

    async def _run_task(
        self,
        task_id: str,
        generate_fn: Any,
        outline: Any,
        theme: str,
        language: str,
        source_type: str | None,
        source_id: str | None,
        queue: asyncio.Queue[dict | None],
    ) -> None:
        """Run the generation function in background, feeding events to the queue."""
        self.db.update_ppt_task_status(task_id, "running")
        try:
            result = await generate_fn(task_id, self.db, queue, outline, theme, language)
            # result is a dict from generate_content_stream; extract fields
            if isinstance(result, dict):
                self.db.set_ppt_task_result(
                    task_id=task_id,
                    presentation_dict=result,
                    model_used=result.get("model_used", "unknown"),
                    generation_time_ms=result.get("generation_time_ms", 0),
                )
            self.db.update_ppt_task_status(task_id, "done")
        except asyncio.CancelledError:
            logger.info("PPT task %s cancelled", task_id)
            self.db.update_ppt_task_status(task_id, "error", "Cancelled")
            raise
        except Exception as e:
            logger.error("PPT task %s failed: %s", task_id, e, exc_info=True)
            self.db.update_ppt_task_status(task_id, "error", str(e))
            await queue.put({"type": "error", "error": str(e)})
        finally:
            await queue.put(None)

    def _on_task_done(self, task_id: str, task: asyncio.Task) -> None:
        """Clean up after a task completes."""
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("PPT task %s finished with error: %s", task_id, exc)
        else:
            logger.info("PPT task %s finished", task_id)

        self._tasks.pop(task_id, None)
        # Keep queue for late subscribers to drain

    def list_tasks(
        self, limit: int = 50, source_type: str | None = None,
    ) -> list[dict]:
        """List past tasks (DB-backed)."""
        return self.db.list_ppt_tasks(limit=limit, source_type=source_type)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task. Cleans up in-memory state too."""
        self._tasks.pop(task_id, None)
        self._queues.pop(task_id, None)
        return self.db.delete_ppt_task(task_id)


# Global singleton (initialized in routes.py after db is available)
_task_manager: PPTTaskManager | None = None


def init_ppt_task_manager(db: Any) -> PPTTaskManager:
    """Initialize the singleton task manager with a DB instance.

    Must be called once at app startup, before any request is served.
    """
    global _task_manager
    _task_manager = PPTTaskManager(db)
    logger.info("PPT task manager initialized with DB-backed persistence")
    return _task_manager


def get_ppt_task_manager() -> PPTTaskManager:
    """Get the singleton task manager. Raises if not initialized."""
    global _task_manager
    if _task_manager is None:
        raise RuntimeError(
            "PPT task manager not initialized. Call init_ppt_task_manager(db) "
            "in _register_agent_routes before serving requests."
        )
    return _task_manager


def reset_ppt_task_manager_for_testing() -> None:
    """Reset singleton — for tests only."""
    global _task_manager
    _task_manager = None
