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


def get_wiki_id(request: Request) -> str | None:
    return request.query_params.get("wiki_id")


@router.post("/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id")
    wiki_id = body.get("wiki_id")

    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()

    async def event_generator():
        async for event in service.chat(
            message=message,
            session_id=session_id,
            wiki_id=wiki_id,
            jwt_token=jwt_token,
        ):
            yield {
                "event": "message",
                "data": json.dumps(event),
            }

    return EventSourceResponse(event_generator())


@router.get("/sessions")
async def list_sessions():
    service = get_agent_service()
    sessions = service.db.list_sessions()
    return {"sessions": sessions}


@router.post("/sessions")
async def create_session(request: Request):
    body = await request.json()
    wiki_id = body.get("wiki_id")
    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()
    session_id = service.db.create_session(wiki_id, jwt_token)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    service = get_agent_service()
    session = service.db.get_session(session_id)
    if session is None:
        return {"error": "Session not found"}
    return session


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 50, before: str | None = None):
    service = get_agent_service()
    messages = service.db.get_messages(session_id, limit=limit, before=before)
    return {"messages": messages, "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    service = get_agent_service()
    deleted = service.db.delete_session(session_id)
    return {"deleted": deleted}


@router.get("/sessions/recent")
async def get_recent_wiki(session_id: str | None = None):
    service = get_agent_service()
    if session_id:
        session = service.db.get_session(session_id)
        if session:
            return {"recent_wiki_id": session.get("wiki_id")}
    return {"recent_wiki_id": None}


@router.post("/sessions/recent")
async def set_recent_wiki(session_id: str, wiki_id: str):
    service = get_agent_service()
    service.db.update_session_wiki(session_id, wiki_id)
    return {"updated": True}


# --- Dream endpoints ---

@router.get("/dream/log")
async def dream_log(request: Request, limit: int = 20):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_dream_log(wiki_id, limit)


@router.post("/dream/run")
async def dream_run(request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.run_dream(wiki_id)


@router.get("/dream/proposals")
async def dream_proposals(request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_dream_proposals(wiki_id)


@router.post("/dream/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str):
    service = get_agent_service()
    return service.approve_proposal(proposal_id)


@router.post("/dream/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    service = get_agent_service()
    return service.reject_proposal(proposal_id)


@router.post("/dream/proposals/batch-approve")
async def batch_approve_proposals(body: dict):
    ids = body.get("ids", [])
    service = get_agent_service()
    return service.batch_approve_proposals(ids)


@router.post("/dream/proposals/apply")
async def apply_proposals(body: dict):
    wiki_id = body.get("wiki_id")
    ids = body.get("ids")
    service = get_agent_service()
    return await service.apply_proposals(wiki_id, ids)


# --- Notifications endpoints ---

@router.get("/notifications")
async def list_notifications(request: Request, unread_only: bool = False):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.list_notifications(wiki_id, unread_only)


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    service = get_agent_service()
    return service.mark_notification_read(notification_id)


# --- Ingest endpoints ---

@router.get("/ingest/log")
async def ingest_log(request: Request, limit: int = 20):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_ingest_log(wiki_id, limit)


@router.get("/ingest/log/{ingest_id}")
async def ingest_changes(ingest_id: str):
    service = get_agent_service()
    return service.get_ingest_entry(ingest_id)


@router.post("/ingest/log/{ingest_id}/revert")
async def revert_ingest(ingest_id: str):
    return {"status": "error", "error": "Revert not implemented - ingest is append-only"}


# --- Status endpoint ---

@router.get("/status")
async def agent_status(request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_agent_status(wiki_id)


# --- Confirmations endpoints ---

@router.get("/confirmations")
async def list_confirmations(request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.list_confirmations(wiki_id)


@router.post("/confirmations/{confirmation_id}")
async def approve_confirmation(confirmation_id: str, request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.approve_confirmation(confirmation_id, wiki_id)


@router.delete("/confirmations/{confirmation_id}")
async def reject_confirmation(confirmation_id: str, request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.reject_confirmation(confirmation_id, wiki_id)


@router.post("/confirmations/batch")
async def batch_approve(body: dict, request: Request):
    ids = body.get("ids", [])
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.batch_approve_confirmations(ids, wiki_id)


# --- Tools endpoint ---

@router.get("/tools")
async def list_tools(request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    if wiki_id:
        registry = service._get_tool_registry(wiki_id)
    else:
        registry = service._get_tool_registry(None)
    return {"tools": registry.list_tools()}