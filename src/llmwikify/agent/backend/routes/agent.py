"""Agent Backend Routes - Agent chat API with SSE support."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from ..service import AgentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

AGENT_SERVICE: AgentService | None = None


def set_agent_service(service: AgentService) -> None:
    global AGENT_SERVICE
    AGENT_SERVICE = service


def get_agent_service() -> AgentService:
    if AGENT_SERVICE is None:
        raise RuntimeError("Agent service not initialized")
    return AGENT_SERVICE


def get_jwt_from_request(request: Request) -> str | None:
    return request.query_params.get("jwt")


@router.post("/chat")
async def chat(request: Request):
    """SSE streaming chat endpoint.

    Body: { "message": str, "session_id"?: str }
    Query: ?jwt=<token>
    """
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id")

    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()

    async def event_generator():
        async for event in service.chat(
            message=message,
            session_id=session_id,
            jwt_token=jwt_token,
        ):
            yield {
                "event": "message",
                "data": json.dumps(event),
            }

    return EventSourceResponse(event_generator())


@router.get("/sessions")
async def list_sessions():
    """List all chat sessions."""
    service = get_agent_service()
    sessions = service.db.list_sessions()
    return {"sessions": sessions}


@router.post("/sessions")
async def create_session(request: Request):
    """Create a new chat session."""
    body = await request.json()
    wiki_id = body.get("wiki_id")
    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()
    session_id = service.db.create_session(wiki_id, jwt_token)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a specific session."""
    service = get_agent_service()
    session = service.db.get_session(session_id)
    if session is None:
        return {"error": "Session not found"}
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    service = get_agent_service()
    deleted = service.db.delete_session(session_id)
    return {"deleted": deleted}


@router.get("/sessions/recent")
async def get_recent_wiki(session_id: str | None = None):
    """Get recent wiki for a session."""
    service = get_agent_service()
    if session_id:
        session = service.db.get_session(session_id)
        if session:
            return {"recent_wiki_id": session.get("wiki_id")}
    return {"recent_wiki_id": None}


@router.post("/sessions/recent")
async def set_recent_wiki(session_id: str, wiki_id: str):
    """Set recent wiki for a session."""
    service = get_agent_service()
    service.db.update_session_wiki(session_id, wiki_id)
    return {"updated": True}


@router.get("/confirmations")
async def list_confirmations():
    """List pending confirmations grouped by type."""
    service = get_agent_service()
    groups = service.get_pending_by_group()
    return groups


@router.post("/confirmations/{confirmation_id}")
async def approve_confirmation(confirmation_id: str):
    """Approve a pending confirmation."""
    service = get_agent_service()
    result = await service.approve_confirmation(confirmation_id)
    return result


@router.delete("/confirmations/{confirmation_id}")
async def reject_confirmation(confirmation_id: str):
    """Reject a pending confirmation."""
    service = get_agent_service()
    result = await service.reject_confirmation(confirmation_id)
    return result


@router.post("/confirmations/batch")
async def batch_approve(body: dict):
    """Batch approve confirmations."""
    ids = body.get("ids", [])
    service = get_agent_service()
    results = []
    for cid in ids:
        result = await service.approve_confirmation(cid)
        results.append(result)
    return {"approved": len(ids), "results": results}


@router.get("/tools")
async def list_tools():
    """List available agent tools."""
    from ..tools import WikiToolRegistry
    from llmwikify.core import WikiRegistry
    registry = WikiRegistry.get_instance()
    default_wiki = registry.get_default_wiki()
    if default_wiki is None:
        return {"tools": []}
    tool_registry = WikiToolRegistry(default_wiki)
    return {"tools": tool_registry.list_tools()}