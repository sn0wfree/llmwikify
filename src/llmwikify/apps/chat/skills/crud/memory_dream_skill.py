"""memory_dream_skill — Phase 6: long-term fact extraction from chat history.

Thin wrapper around ``apps/chat/memory/Dream``. The Dream instance
is passed via ``ctx.config['memory_manager'].dream``.

Borrowed from nanobot agent/memory.py:859 (Dream class). Distinct
from the existing ``DreamSkill`` (crud/dream_skill.py) which wraps
``apps/agent/dream_editor/`` for wiki edit proposals.

Actions:

  - ``run()`` — run Dream (full incremental scan since last cursor)
  - ``run_for_session(session_id)`` — Dream scoped to one session

Slash command: ``/memory_dream`` (avoid conflict with existing
``/dream`` which drives wiki edit proposals).
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


def _get_dream(ctx: SkillContext) -> Any | SkillResult:
    mgr = ctx.config.get("memory_manager") if ctx.config else None
    if mgr is None:
        return SkillResult.fail("memory_manager not configured in ctx.config")
    dream = getattr(mgr, "dream", None)
    if dream is None:
        return SkillResult.fail(
            "memory_manager.dream not configured (no LLM provider at MemoryManager construction)"
        )
    return dream


# ─── Action handlers ──────────────────────────────────────────────


async def _run(args: dict, ctx: SkillContext) -> SkillResult:
    dream = _get_dream(ctx)
    if isinstance(dream, SkillResult):
        return dream
    try:
        result = await dream.run()
        return SkillResult.ok(result.to_dict())
    except Exception as e:
        logger.exception("memory_dream run failed")
        return SkillResult.fail(f"memory_dream run failed: {e!r}")


async def _run_for_session(args: dict, ctx: SkillContext) -> SkillResult:
    dream = _get_dream(ctx)
    if isinstance(dream, SkillResult):
        return dream
    session_id = args.get("session_id", "") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    try:
        result = await dream.run_for_session(session_id)
        return SkillResult.ok(result.to_dict())
    except Exception as e:
        logger.exception("memory_dream run_for_session failed")
        return SkillResult.fail(
            f"memory_dream run_for_session failed: {e!r}"
        )


# ─── Skill declaration ─────────────────────────────────────────


class MemoryDreamSkill(Skill):
    """CRUD: run/run_for_session long-term fact extractor (Phase 6)."""

    name = "memory_dream"
    description = (
        "Run long-term fact extraction (Dream processor) on chat history. "
        "Use when you want to convert recent consolidations into durable facts."
    )
    actions = {
        "run": SkillAction(
            name="run",
            description=(
                "Run Dream incrementally on all sessions since last cursor. "
                "Returns {consolidations_scanned, facts_extracted, facts_written, cursor}."
            ),
            handler=_run,
            input_schema={"type": "object", "properties": {}},
            action_type="write",
            tags=["memory"],
        ),
        "run_for_session": SkillAction(
            name="run_for_session",
            description=(
                "Run Dream scoped to one session regardless of cursor. "
                "Useful for forcing a session's facts to be extracted."
            ),
            handler=_run_for_session,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to process (default: ctx.session_id)",
                    },
                },
            },
            action_type="write",
            tags=["memory"],
        ),
    }


memory_dream_skill = MemoryDreamSkill()


__all__ = ["MemoryDreamSkill", "memory_dream_skill"]
