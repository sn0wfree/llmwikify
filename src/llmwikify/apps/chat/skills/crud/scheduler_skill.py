"""scheduler_skill — CRUD: add_job/list_jobs/remove_job/trigger cron scheduler.

Thin wrapper around ``apps/agent/scheduler/`` (WikiScheduler).
The scheduler is passed via ``ctx.config['scheduler']``.

Actions:

  - ``add_job(name, cron_expr, handler_ref)`` — register a task
  - ``list_jobs()`` — list all registered tasks
  - ``remove_job(name)`` — unregister a task
  - ``trigger(name)`` — manually trigger a task

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#30)
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


def _get_scheduler(ctx: SkillContext) -> Any | SkillResult:
    sched = ctx.config.get("scheduler") if ctx.config else None
    if sched is None:
        return SkillResult.fail("scheduler not configured in ctx.config")
    return sched


# ─── Action handlers ──────────────────────────────────────────────


async def _add_job(args: dict, ctx: SkillContext) -> SkillResult:
    sched = _get_scheduler(ctx)
    if isinstance(sched, SkillResult):
        return sched
    name = args.get("name", "")
    cron_expr = args.get("cron_expr", "")
    if not name or not cron_expr:
        return SkillResult.fail("name and cron_expr are required")
    handler_ref = args.get("handler_ref", "")

    # Create a placeholder handler; real wiring happens at startup
    def _placeholder() -> dict:
        return {"status": "placeholder", "task": name}

    sched.add_task(
        name=name,
        cron_expr=cron_expr,
        handler=_placeholder,
        description=args.get("description", ""),
        enabled=args.get("enabled", True),
        is_write=args.get("is_write", False),
    )
    return SkillResult.ok({"added": True, "name": name, "cron_expr": cron_expr})


async def _list_jobs(args: dict, ctx: SkillContext) -> SkillResult:
    sched = _get_scheduler(ctx)
    if isinstance(sched, SkillResult):
        return sched
    tasks = sched.list_tasks()
    return SkillResult.ok({"jobs": tasks, "count": len(tasks)})


async def _remove_job(args: dict, ctx: SkillContext) -> SkillResult:
    sched = _get_scheduler(ctx)
    if isinstance(sched, SkillResult):
        return sched
    name = args.get("name", "")
    if not name:
        return SkillResult.fail("name is required")
    sched.remove_task(name)
    return SkillResult.ok({"removed": True, "name": name})


async def _trigger(args: dict, ctx: SkillContext) -> SkillResult:
    sched = _get_scheduler(ctx)
    if isinstance(sched, SkillResult):
        return sched
    name = args.get("name", "")
    if not name:
        return SkillResult.fail("name is required")
    task = sched.get_task(name)
    if task is None:
        return SkillResult.fail(f"task {name!r} not found")
    try:
        result = task.run()
        return SkillResult.ok({"triggered": True, "name": name, "result": result})
    except Exception as e:
        return SkillResult.fail(f"trigger failed: {e!r}")


# ─── Skill declaration ─────────────────────────────────────────


class SchedulerSkill(Skill):
    """CRUD: add_job/list_jobs/remove_job/trigger cron scheduler."""

    name = "scheduler"
    description = "Manage scheduled tasks (add, list, remove, trigger)"
    actions = {
        "add_job": SkillAction(
            name="add_job",
            description="Register a new scheduled task with a cron expression",
            handler=_add_job,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Task name (unique identifier)"},
                    "cron_expr": {"type": "string", "description": "Cron expression (e.g. '0 */2 * * *')"},
                    "handler_ref": {"type": "string", "description": "Handler function reference (optional)"},
                    "description": {"type": "string", "description": "Human-readable description"},
                    "enabled": {"type": "boolean", "description": "Start enabled (default true)", "default": True},
                    "is_write": {"type": "boolean", "description": "Whether this is a write task (default false)", "default": False},
                },
                "required": ["name", "cron_expr"],
            },
            action_type="write",
        ),
        "list_jobs": SkillAction(
            name="list_jobs",
            description="List all registered scheduled tasks",
            handler=_list_jobs,
            input_schema={"type": "object", "properties": {}},
        ),
        "remove_job": SkillAction(
            name="remove_job",
            description="Remove a scheduled task by name",
            handler=_remove_job,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Task name to remove"},
                },
                "required": ["name"],
            },
            action_type="write",
        ),
        "trigger": SkillAction(
            name="trigger",
            description="Manually trigger a scheduled task immediately",
            handler=_trigger,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Task name to trigger"},
                },
                "required": ["name"],
            },
            action_type="write",
        ),
    }


scheduler_skill = SchedulerSkill()


__all__ = ["SchedulerSkill", "scheduler_skill"]
