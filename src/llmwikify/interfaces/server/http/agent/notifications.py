"""Notifications 路由 — 系统通知。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from llmwikify.interfaces.server.http._helpers import get_wiki_id
from llmwikify.interfaces.server.http.agent._common import (
    get_agent_service,
    router,
)


@router.get("/notifications")
async def list_notifications(request: Request, unread_only: bool = False) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.list_notifications(wiki_id, unread_only)


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str) -> Any:
    service = get_agent_service()
    return service.mark_notification_read(notification_id)
