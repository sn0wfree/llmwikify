"""goal_skill — sustained per-session objective (Phase 8).

Borrowed from nanobot v0.2.1 ``long_task`` / ``complete_goal`` tools
(see ``nanobot/agent/tools/long_task.py`` + ``skills/long-goal/SKILL.md``)
adapted to llmwikify's SkillAction framework.

Two actions:

  - ``start_long_task(goal, ui_summary?)`` — register one sustained
    objective on the current session. Errors out if a goal is already
    active; the LLM must call ``complete_goal`` first to replace it.
  - ``complete_goal(recap?)`` — close bookkeeping for the active goal.
    Recap is honest text describing what happened (success, cancelled,
    pivoted). No-op message when no goal is active.

Storage: ``chat_sessions.metadata`` JSON column, key
``goal_state``. Read by :func:`goal_state_runtime_lines` so the
PromptBuilder can mirror the active goal into every system prompt.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from llmwikify.apps.chat.agent.goal_state import (
    GOAL_STATE_KEY,
    goal_state_raw,
    parse_goal_state,
)
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now().isoformat()


def _get_session_repo(ctx: SkillContext) -> Any | SkillResult:
    """Return ChatSessionRepository (via ChatDatabase facade) or fail."""
    db = ctx.db
    if db is None and ctx.config:
        mm = ctx.config.get("memory_manager")
        if mm is not None:
            db = getattr(mm, "db", None) or getattr(mm, "app_db", None)
    if db is None:
        return SkillResult.fail(
            "goal skill: no chat_db available in SkillContext",
        )
    # ``db`` may be ChatDatabase facade (has get_session_metadata) or
    # AppDatabase (has .chat). Normalize to the facade.
    if hasattr(db, "chat") and not hasattr(db, "get_session_metadata"):
        db = db.chat
    return db


# ─── Action handlers ───────────────────────────────────────────────


async def _start_long_task(args: dict, ctx: SkillContext) -> SkillResult:
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    goal = (args.get("goal") or "").strip()
    if not goal:
        return SkillResult.fail("goal is required")
    ui_summary = (args.get("ui_summary") or "").strip()[:120]

    repo = _get_session_repo(ctx)
    if isinstance(repo, SkillResult):
        return repo

    metadata = repo.get_session_metadata(session_id)
    prior = parse_goal_state(goal_state_raw(metadata))
    if isinstance(prior, dict) and prior.get("status") == "active":
        return SkillResult.fail(
            "A sustained goal is already active. Call complete_goal "
            "with an honest recap before registering a new one.",
            current_goal=prior.get("objective", ""),
        )

    blob = {
        "status": "active",
        "objective": goal,
        "ui_summary": ui_summary,
        "started_at": _iso_now(),
    }
    repo.update_session_metadata(session_id, **{GOAL_STATE_KEY: blob})
    return SkillResult.ok({
        "registered": True,
        "objective": goal,
        "ui_summary": ui_summary,
        "started_at": blob["started_at"],
    })


async def _complete_goal(args: dict, ctx: SkillContext) -> SkillResult:
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    recap = (args.get("recap") or "").strip()

    repo = _get_session_repo(ctx)
    if isinstance(repo, SkillResult):
        return repo

    metadata = repo.get_session_metadata(session_id)
    prior = parse_goal_state(goal_state_raw(metadata))
    if not isinstance(prior, dict) or prior.get("status") != "active":
        return SkillResult.ok({"completed": False, "reason": "no active goal"})

    ended = _iso_now()
    blob = {
        **prior,
        "status": "completed",
        "completed_at": ended,
        "recap": recap,
    }
    repo.update_session_metadata(session_id, **{GOAL_STATE_KEY: blob})
    return SkillResult.ok({
        "completed": True,
        "completed_at": ended,
        "recap": recap,
        "objective": prior.get("objective", ""),
    })


async def _get_goal(args: dict, ctx: SkillContext) -> SkillResult:
    """Read-only inspection helper (handy for UI / debugging)."""
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    repo = _get_session_repo(ctx)
    if isinstance(repo, SkillResult):
        return repo
    metadata = repo.get_session_metadata(session_id)
    goal = parse_goal_state(goal_state_raw(metadata))
    return SkillResult.ok({
        "active": isinstance(goal, dict) and goal.get("status") == "active",
        "goal": goal or {},
    })


# ─── Skill declaration ─────────────────────────────────────────────


_LONG_TASK_DESCRIPTION = (
    "Register ONE sustained objective for this chat session. Use when "
    "the user asks for multi-turn work on a single clear goal (e.g. "
    "research, refactor, build). Write the goal idempotent (state-"
    "oriented, self-contained, bounded, explicit done-ness). The active "
    "goal is mirrored into every system prompt across turns so "
    "compaction cannot hide it. If a goal is already active, call "
    "complete_goal first instead of stacking goals."
)

_COMPLETE_GOAL_DESCRIPTION = (
    "End bookkeeping for the active sustained goal. Use when the goal "
    "is done AND when the user cancels, pivots, or replaces it. The "
    "recap should honestly state what happened (success, cancelled, "
    "partial). After this returns, a new long_task may be registered."
)


class GoalSkill(Skill):
    """Sustained per-session objective tracking (long_task / complete_goal)."""

    name = "goal"
    description = (
        "Track a sustained per-session objective so it survives "
        "compaction and stays visible across turns."
    )
    actions = {
        "start_long_task": SkillAction(
            name="start_long_task",
            description=_LONG_TASK_DESCRIPTION,
            handler=_start_long_task,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (defaults to ctx.session_id).",
                    },
                    "goal": {
                        "type": "string",
                        "description": (
                            "Idempotent objective text (≤4000 chars in "
                            "runtime context). State desired end state, "
                            "boundaries, and done-ness."
                        ),
                    },
                    "ui_summary": {
                        "type": "string",
                        "description": "Optional short label for UI (≤120 chars).",
                    },
                },
                "required": ["goal"],
            },
            action_type="write",
        ),
        "complete_goal": SkillAction(
            name="complete_goal",
            description=_COMPLETE_GOAL_DESCRIPTION,
            handler=_complete_goal,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (defaults to ctx.session_id).",
                    },
                    "recap": {
                        "type": "string",
                        "description": (
                            "Honest recap of what happened: success, "
                            "cancellation, pivot, or partial result."
                        ),
                    },
                },
            },
            action_type="write",
        ),
        "get_goal": SkillAction(
            name="get_goal",
            description="Read the current goal_state blob (active or last completed).",
            handler=_get_goal,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID (defaults to ctx.session_id).",
                    },
                },
            },
        ),
    }


goal_skill = GoalSkill()


__all__ = ["GoalSkill", "goal_skill"]
