"""Background task manager for PPT generation.

Runs PPT generation as independent asyncio.Tasks, decoupled from SSE connections.
Events are buffered in per-task async queues so SSE consumers can subscribe at any time.
"""
from __future__ import annotations

import asyncio
import json
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
    """Manages background PPT generation tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}
        self._status: dict[str, TaskStatus] = {}
        self._results: dict[str, Any] = {}
        self._errors: dict[str, str] = {}

    def create_task(
        self,
        generate_fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Create a new background PPT generation task. Returns task_id."""
        task_id = uuid.uuid4().hex[:12]
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._queues[task_id] = queue
        self._status[task_id] = TaskStatus.PENDING

        task = asyncio.create_task(
            self._run_task(task_id, generate_fn, args, kwargs, queue),
            name=f"ppt-{task_id}",
        )
        self._tasks[task_id] = task
        task.add_done_callback(lambda t, tid=task_id: self._on_task_done(tid, t))
        logger.info("Created PPT task %s", task_id)
        return task_id

    def get_status(self, task_id: str) -> dict[str, Any]:
        """Get current task status."""
        status = self._status.get(task_id, TaskStatus.ERROR)
        result: dict[str, Any] = {"task_id": task_id, "status": status.value}
        if status == TaskStatus.DONE and task_id in self._results:
            result["presentation"] = self._results[task_id]
        if task_id in self._errors:
            result["error"] = self._errors[task_id]
        return result

    async def get_event_stream(self, task_id: str) -> AsyncIterator[dict]:
        """Get an async iterator of events for a task.

        Yields events from the per-task queue. Returns when the task
        completes and all events are consumed.
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
        args: tuple,
        kwargs: dict,
        queue: asyncio.Queue[dict | None],
    ) -> None:
        """Run the generation function in background, feeding events to the queue."""
        self._status[task_id] = TaskStatus.RUNNING
        try:
            result = await generate_fn(task_id, queue, *args, **kwargs)
            self._results[task_id] = result
            self._status[task_id] = TaskStatus.DONE
        except asyncio.CancelledError:
            logger.info("PPT task %s cancelled", task_id)
            self._status[task_id] = TaskStatus.ERROR
            self._errors[task_id] = "Cancelled"
            raise
        except Exception as e:
            logger.error("PPT task %s failed: %s", task_id, e, exc_info=True)
            self._status[task_id] = TaskStatus.ERROR
            self._errors[task_id] = str(e)
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


# Global singleton
_task_manager: PPTTaskManager | None = None


def get_ppt_task_manager() -> PPTTaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = PPTTaskManager()
    return _task_manager
