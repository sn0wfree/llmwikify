"""Scheduler - Cron-based task scheduler for Agent system tasks.

Uses croniter for cron expression parsing.
System tasks:
- Dream update (every 2 hours)
- Check raw/ (every 30 minutes)
- Daily lint (every day at 22:00)
- Weekly gap analysis (every Monday at 9:00)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


class ScheduledTask:
    """Represents a scheduled task."""

    def __init__(
        self,
        name: str,
        cron_expr: str,
        handler: Callable,
        description: str = "",
        enabled: bool = True,
        is_write: bool = False,
    ):
        self.name = name
        self.cron_expr = cron_expr
        self.handler = handler
        self.description = description
        self.enabled = enabled
        self.is_write = is_write
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None
        self.run_count = 0
        self.last_result: Any = None

        if HAS_CRONITER:
            self._croniter = croniter(cron_expr, datetime.now(timezone.utc))
            self.next_run = self._croniter.get_next(datetime)
        else:
            self._croniter = None

    def should_run(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        if self.next_run is None:
            return True
        return now >= self.next_run

    def run(self) -> Any:
        try:
            result = self.handler()
            self.last_run = datetime.now(timezone.utc)
            self.run_count += 1
            self.last_result = result
            if self._croniter:
                self.next_run = self._croniter.get_next(datetime)
            return result
        except Exception as e:
            logger.error(f"Task {self.name} failed: {e}")
            self.last_result = {"error": str(e)}
            raise

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cron_expr": self.cron_expr,
            "description": self.description,
            "enabled": self.enabled,
            "is_write": self.is_write,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
        }


class WikiScheduler:
    """Cron scheduler for wiki system tasks."""

    def __init__(self, data_dir: Path | None = None):
        self._tasks: dict[str, ScheduledTask] = {}
        self.data_dir = data_dir
        self._state_file = data_dir / "scheduler.json" if data_dir else None

    def add_task(
        self,
        name: str,
        cron_expr: str,
        handler: Callable,
        description: str = "",
        enabled: bool = True,
        is_write: bool = False,
    ) -> ScheduledTask:
        task = ScheduledTask(name, cron_expr, handler, description, enabled, is_write)
        self._tasks[name] = task
        return task

    def remove_task(self, name: str) -> None:
        self._tasks.pop(name, None)

    def get_task(self, name: str) -> ScheduledTask | None:
        return self._tasks.get(name)

    def list_tasks(self) -> list[dict]:
        return [task.to_dict() for task in self._tasks.values()]

    def enable_task(self, name: str) -> None:
        task = self._tasks.get(name)
        if task:
            task.enabled = True

    def disable_task(self, name: str) -> None:
        task = self._tasks.get(name)
        if task:
            task.enabled = False

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Check and run all due tasks. Returns list of results."""
        if now is None:
            now = datetime.now(timezone.utc)

        results = []
        for task in self._tasks.values():
            if task.should_run(now):
                try:
                    result = task.run()
                    results.append({
                        "task": task.name,
                        "success": True,
                        "result": result,
                        "is_write": task.is_write,
                    })
                except Exception as e:
                    results.append({
                        "task": task.name,
                        "success": False,
                        "error": str(e),
                        "is_write": task.is_write,
                    })
        return results

    def save_state(self) -> None:
        if self._state_file:
            state = {
                "tasks": {
                    name: task.to_dict() for name, task in self._tasks.items()
                }
            }
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(state, indent=2))

    def load_state(self) -> None:
        if self._state_file and self._state_file.exists():
            try:
                state = json.loads(self._state_file.read_text())
                for name, task_data in state.get("tasks", {}).items():
                    if name in self._tasks:
                        task = self._tasks[name]
                        if task_data.get("last_run"):
                            task.last_run = datetime.fromisoformat(task_data["last_run"])
                        if task_data.get("run_count"):
                            task.run_count = task_data["run_count"]
            except Exception as e:
                logger.warning(f"Failed to load scheduler state: {e}")

    def register_system_tasks(
        self,
        wiki: Any,
        dream_editor: Any | None = None,
        notification_manager: Any | None = None,
    ) -> None:
        """Register default wiki system tasks.

        Task classification:
        - Auto tasks (is_write=False): read-only or safe operations
        - Manual tasks (is_write=True): write operations, generate proposals
        """

        def dream_task():
            if dream_editor:
                result = dream_editor.run_dream()
                if notification_manager and result.get("pending_review", 0) > 0:
                    notification_manager.add(
                        "info",
                        f"Dream generated {result.get('pending_review', 0)} proposals for review",
                        data=result,
                    )
                return result
            return {"status": "skipped", "reason": "no dream editor"}

        def check_raw_task():
            if hasattr(wiki, "raw_dir") and wiki.raw_dir.exists():
                files = list(wiki.raw_dir.rglob("*"))
                return {"status": "ok", "file_count": len(files)}
            return {"status": "ok", "file_count": 0}

        def daily_lint():
            return wiki.lint(mode="check", limit=10)

        def weekly_gaps():
            return wiki.lint(generate_investigations=True, limit=20)

        # Auto tasks (read-only, safe to execute automatically)
        self.add_task(
            "check_raw",
            "*/30 * * * *",
            check_raw_task,
            "Monitor raw/ directory for new files",
            is_write=False,
        )
        self.add_task(
            "daily_lint",
            "0 22 * * *",
            daily_lint,
            "Daily wiki health check",
            is_write=False,
        )
        self.add_task(
            "weekly_gaps",
            "0 9 * * 1",
            weekly_gaps,
            "Weekly knowledge gap analysis",
            is_write=False,
        )

        # Manual tasks (write operations, generate proposals for review)
        self.add_task(
            "dream_update",
            "0 */2 * * *",
            dream_task,
            "Analyze QuerySink and generate Dream proposals",
            is_write=True,
        )
