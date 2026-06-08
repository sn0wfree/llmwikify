"""memory_skill — CRUD: append/query/summarize/clear conversation memory.

Thin wrapper around ``apps/agent/memory/`` (ConversationMemory +
SinkMemory). The manager is passed via ``ctx.config['memory_manager']``.

Actions:

  - ``append(role, content, metadata)`` — add a conversation entry
  - ``query(limit)`` — get recent conversation entries
  - ``summarize()`` — get pending knowledge sink pages
  - ``clear()`` — delete all conversation history

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#28)
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


def _get_manager(ctx: SkillContext) -> Any:
    mgr = ctx.config.get("memory_manager") if ctx.config else None
    if mgr is None:
        return SkillResult.fail("memory_manager not configured in ctx.config")
    return mgr


# ─── Action handlers ──────────────────────────────────────────────


async def _append(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    role = args.get("role", "user")
    content = args.get("content", "")
    if not content:
        return SkillResult.fail("content is required")
    metadata = args.get("metadata")
    mgr.store_conversation(role, content, metadata)
    return SkillResult.ok({"appended": True, "role": role})


async def _query(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    limit = args.get("limit", 20)
    entries = mgr.get_context(max_messages=limit)
    return SkillResult.ok({"entries": entries, "count": len(entries)})


async def _summarize(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    pending = mgr.get_pending_work()
    return SkillResult.ok(pending)


async def _clear(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    mgr.conversation.clear()
    return SkillResult.ok({"cleared": True})


# ─── Skill declaration ─────────────────────────────────────────


class MemorySkill(Skill):
    """CRUD: append/query/summarize/clear conversation memory."""

    name = "memory"
    description = "Manage conversation memory and knowledge sink"
    actions = {
        "append": SkillAction(
            name="append",
            description="Append a conversation entry (role + content + optional metadata)",
            handler=_append,
            input_schema={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "Message role (user/assistant/system)", "default": "user"},
                    "content": {"type": "string", "description": "Message content"},
                    "metadata": {"type": "object", "description": "Optional metadata dict"},
                },
                "required": ["content"],
            },
        ),
        "query": SkillAction(
            name="query",
            description="Get recent conversation entries",
            handler=_query,
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return (default 20)", "default": 20},
                },
            },
        ),
        "summarize": SkillAction(
            name="summarize",
            description="Get pending knowledge sink pages and status",
            handler=_summarize,
            input_schema={"type": "object", "properties": {}},
        ),
        "clear": SkillAction(
            name="clear",
            description="Delete all conversation history",
            handler=_clear,
            input_schema={"type": "object", "properties": {}},
            action_type="write",
        ),
    }


memory_skill = MemorySkill()


__all__ = ["MemorySkill", "memory_skill"]
