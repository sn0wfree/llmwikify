"""memory_skill — CRUD: add/list/search/clear conversation memory.

Thin wrapper around ``apps/chat/memory/`` (ConversationStore).
The manager is passed via ``ctx.config['memory_manager']``.

Actions:

  - ``add(session_id, role, content)`` — add a conversation entry
  - ``list(session_id, limit)`` — get recent conversation entries
  - ``search(session_id, query, limit)`` — search by content substring
  - ``clear(session_id)`` — delete all conversation history

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


def _get_memory(ctx: SkillContext) -> Any | SkillResult:
    mgr = ctx.config.get("memory_manager") if ctx.config else None
    if mgr is None:
        return SkillResult.fail("memory_manager not configured in ctx.config")
    return mgr


# ─── Action handlers ──────────────────────────────────────────────


async def _add(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_memory(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    role = args.get("role", "user")
    content = args.get("content", "")
    if not content:
        return SkillResult.fail("content is required")
    msg_id = mgr.conversation.add(session_id, role, content)
    return SkillResult.ok({"added": True, "id": msg_id, "role": role})


async def _list(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_memory(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    limit = args.get("limit", 50)
    entries = mgr.conversation.list(session_id, limit=limit)
    return SkillResult.ok({"entries": entries, "count": len(entries)})


async def _search(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_memory(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    limit = args.get("limit", 10)
    entries = mgr.conversation.search(session_id, query, limit)
    return SkillResult.ok({"entries": entries, "count": len(entries)})


async def _clear(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_memory(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    session_id = args.get("session_id") or ctx.session_id
    if not session_id:
        return SkillResult.fail("session_id is required")
    # Clear context entries (conversation is append-only log)
    count = mgr.context.clear(session_id)
    return SkillResult.ok({"cleared": True, "entries_removed": count})


# ─── Skill declaration ─────────────────────────────────────────


class MemorySkill(Skill):
    """CRUD: add/list/search/clear conversation memory."""

    name = "memory"
    description = "Manage conversation memory and context entries"
    actions = {
        "add": SkillAction(
            name="add",
            description="Add a conversation entry (role + content)",
            handler=_add,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID (defaults to ctx.session_id)"},
                    "role": {"type": "string", "description": "Message role (user/assistant/system)", "default": "user"},
                    "content": {"type": "string", "description": "Message content"},
                },
                "required": ["content"],
            },
        ),
        "list": SkillAction(
            name="list",
            description="Get recent conversation entries",
            handler=_list,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID (defaults to ctx.session_id)"},
                    "limit": {"type": "integer", "description": "Max entries to return (default 50)", "default": 50},
                },
            },
        ),
        "search": SkillAction(
            name="search",
            description="Search conversation entries by content substring",
            handler=_search,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID (defaults to ctx.session_id)"},
                    "query": {"type": "string", "description": "Search query (substring match)"},
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        "clear": SkillAction(
            name="clear",
            description="Clear context entries for a session",
            handler=_clear,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID (defaults to ctx.session_id)"},
                },
            },
            action_type="write",
        ),
    }


memory_skill = MemorySkill()


__all__ = ["MemorySkill", "memory_skill"]
