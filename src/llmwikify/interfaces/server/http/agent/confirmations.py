"""Confirmations 路由 — 工具调用确认审批。"""

from __future__ import annotations

from typing import Any

import json

from fastapi import Request
from sse_starlette import EventSourceResponse

from llmwikify.interfaces.server.http._helpers import get_wiki_id
from llmwikify.interfaces.server.http._models import (
    ApprovalRequest,
    BatchApproveRequest,
)
from llmwikify.interfaces.server.http.agent._common import (
    JsonBodyHelper,
    get_agent_service,
    router,
)
from llmwikify.interfaces.server.http.agent._sse import (
    HEARTBEAT_INTERVAL,
    _sse_stream,
)


@router.get("/confirmations")
async def list_confirmations(request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.list_confirmations(wiki_id)


@router.post("/confirmations/{confirmation_id}")
async def approve_confirmation(confirmation_id: str, request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    body = {}
    raw = await request.body()
    if raw:
        body = json.loads(raw)
    arguments = body.get("arguments")
    # v0.40: response can be "once", "always", or default "once"
    response = body.get("response", "once")
    if response not in ("once", "always", "reject"):
        response = "once"
    return await service.approve_confirmation(
        confirmation_id, wiki_id,
        arguments=arguments, response=response,
    )


@router.post("/confirmations/{confirmation_id}/approve-and-continue")
async def approve_and_continue(confirmation_id: str, request: Request) -> Any:
    """Approve confirmation, execute tool, and stream LLM follow-up."""
    req = await JsonBodyHelper.execute(request, ApprovalRequest)
    service = get_agent_service()

    source = service.approve_confirmation_and_continue(
        confirmation_id=confirmation_id,
        session_id=req.session_id,
        wiki_id=req.wiki_id,
        arguments=req.arguments,
    )

    return EventSourceResponse(
        _sse_stream(source, session_id=req.session_id),
        ping=HEARTBEAT_INTERVAL,
    )


@router.delete("/confirmations/{confirmation_id}")
async def reject_confirmation(confirmation_id: str, request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.reject_confirmation(confirmation_id, wiki_id)


@router.post("/confirmations/batch")
async def batch_approve(request: Request) -> Any:
    req = await JsonBodyHelper.execute(request, BatchApproveRequest)
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.batch_approve_confirmations(req.ids, wiki_id)
