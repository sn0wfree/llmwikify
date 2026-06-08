"""notify_skill — CRUD: list/mark_read/subscribe notification manager.

Thin wrapper around ``apps/agent/notifications/``
(NotificationManager). The manager is passed via
``ctx.config['notification_manager']``.

Actions:

  - ``list(read_filter)`` — list notifications (all/unread/read)
  - ``mark_read(notification_id)`` — mark a notification as read
  - ``subscribe(event_type)`` — placeholder for future pub/sub

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#29)
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


def _get_manager(ctx: SkillContext) -> Any | SkillResult:
    mgr = ctx.config.get("notification_manager") if ctx.config else None
    if mgr is None:
        return SkillResult.fail("notification_manager not configured in ctx.config")
    return mgr


# ─── Action handlers ──────────────────────────────────────────────


async def _list_notifications(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    read_filter = args.get("read_filter", "all")
    if read_filter == "unread":
        entries = mgr.list_unread()
    elif read_filter == "read":
        entries = [n for n in mgr.list_all() if n.get("read")]
    else:
        entries = mgr.list_all()
    return SkillResult.ok({"notifications": entries, "count": len(entries)})


async def _mark_read(args: dict, ctx: SkillContext) -> SkillResult:
    mgr = _get_manager(ctx)
    if isinstance(mgr, SkillResult):
        return mgr
    nid = args.get("notification_id", "")
    if not nid:
        return SkillResult.fail("notification_id is required")
    ok = mgr.mark_read(nid)
    if not ok:
        return SkillResult.fail(f"notification {nid!r} not found")
    return SkillResult.ok({"marked_read": True, "notification_id": nid})


async def _subscribe(args: dict, ctx: SkillContext) -> SkillResult:
    # Placeholder for future pub/sub
    event_type = args.get("event_type", "all")
    return SkillResult.ok({
        "subscribed": True,
        "event_type": event_type,
        "_note": "subscribe is a placeholder; notifications are currently poll-based",
    })


# ─── Skill declaration ─────────────────────────────────────────


class NotifySkill(Skill):
    """CRUD: list/mark_read/subscribe notification manager."""

    name = "notify"
    description = "Manage notifications (list, mark read, subscribe)"
    actions = {
        "list": SkillAction(
            name="list",
            description="List notifications, optionally filtered by read status",
            handler=_list_notifications,
            input_schema={
                "type": "object",
                "properties": {
                    "read_filter": {
                        "type": "string",
                        "description": "Filter: 'all' (default), 'unread', or 'read'",
                        "default": "all",
                    },
                },
            },
        ),
        "mark_read": SkillAction(
            name="mark_read",
            description="Mark a notification as read by ID",
            handler=_mark_read,
            input_schema={
                "type": "object",
                "properties": {
                    "notification_id": {"type": "string", "description": "Notification UUID"},
                },
                "required": ["notification_id"],
            },
        ),
        "subscribe": SkillAction(
            name="subscribe",
            description="Subscribe to notification events (placeholder)",
            handler=_subscribe,
            input_schema={
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Event type to subscribe to", "default": "all"},
                },
            },
        ),
    }


notify_skill = NotifySkill()


__all__ = ["NotifySkill", "notify_skill"]
