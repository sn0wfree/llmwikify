"""Sessions 路由 — /chat + 会话 CRUD。"""

from __future__ import annotations

from fastapi import Request
from sse_starlette import EventSourceResponse

from llmwikify.interfaces.server.http._helpers import get_jwt_from_request
from llmwikify.interfaces.server.http._models import (
    ChatRequest,
    CreateSessionRequest,
    EditMessageRequest,
    RevertRequest,
)
from llmwikify.interfaces.server.http.agent._common import (
    JsonBodyHelper,
    get_agent_service,
    router,
)
from llmwikify.interfaces.server.http.agent._sse import (
    _STUDY_TRIGGER,
    HEARTBEAT_INTERVAL,
    STREAM_TIMEOUT,
    STUDY_STREAM_TIMEOUT,
    _sse_stream,
)

# ─── /chat（SSE）───────────────────────────────────────────────

@router.post("/chat")
async def chat(request: Request):
    req = await JsonBodyHelper.execute(request, ChatRequest)
    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()

    # Issue#14: detect /study research triggers and use a longer
    # stream timeout so long-running research workflows aren't cut
    # off mid-run (the default 5min is too short for 6-step research).
    is_study = (
        req.message.lstrip().lower().startswith(_STUDY_TRIGGER)
    )
    stream_timeout = STUDY_STREAM_TIMEOUT if is_study else STREAM_TIMEOUT

    source = service.chat(
        message=req.message,
        session_id=req.session_id,
        wiki_id=req.wiki_id,
        jwt_token=jwt_token,
    )

    return EventSourceResponse(
        _sse_stream(source, session_id=req.session_id, timeout=stream_timeout),
        ping=HEARTBEAT_INTERVAL,
    )


# ─── Sessions CRUD ─────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions():
    service = get_agent_service()
    sessions = service.db.list_chat_sessions()
    return {"sessions": sessions}


@router.post("/sessions")
async def create_session(request: Request):
    req = await JsonBodyHelper.execute(request, CreateSessionRequest)
    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()
    session_id = service.db.create_chat_session(req.wiki_id, jwt_token)
    return {"session_id": session_id}


@router.get("/sessions/status")
async def get_all_session_status():
    """Get status for all active sessions."""
    service = get_agent_service()
    return {"sessions": service.get_all_session_status()}


@router.get("/sessions/recent")
async def get_recent_wiki(session_id: str | None = None):
    service = get_agent_service()
    if session_id:
        session = service.db.get_chat_session(session_id)
        if session:
            return {"recent_wiki_id": session.get("wiki_id")}
    return {"recent_wiki_id": None}


@router.post("/sessions/recent")
async def set_recent_wiki(session_id: str, wiki_id: str):
    service = get_agent_service()
    service.db.update_chat_session_wiki(session_id, wiki_id)
    return {"updated": True}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    service = get_agent_service()
    session = service.db.get_chat_session(session_id)
    if session is None:
        return {"error": "Session not found"}
    return session


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 50, before: str | None = None):
    service = get_agent_service()
    messages = service.db.get_chat_messages(session_id, limit=limit, before=before)
    return {"messages": messages, "session_id": session_id}


@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    """Get event log for a session (for debugging/replay)."""
    service = get_agent_service()
    events = service.chat_service.event_log.get_events(session_id)
    return {"events": events, "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    service = get_agent_service()
    deleted = service.delete_session(session_id)
    return {"deleted": deleted}


@router.post("/sessions/{session_id}/revert")
async def revert_session(session_id: str, request: Request):
    """Revert session to a specific message. All messages after it are marked reverted."""
    req = await JsonBodyHelper.execute(request, RevertRequest)
    service = get_agent_service()
    count = service.revert_session(session_id, req.message_id)
    return {"reverted": count, "session_id": session_id}


@router.put("/sessions/{session_id}/messages/{message_id}")
async def edit_message(session_id: str, message_id: str, request: Request):
    """Edit a user message's content in-place."""
    req = await JsonBodyHelper.execute(request, EditMessageRequest)
    service = get_agent_service()
    ok = service.edit_message(message_id, req.content)
    if not ok:
        return {"error": "message not found"}
    # Evict context so next chat() reloads from DB
    service.chat_service.context_manager.remove(session_id)
    return {"updated": True, "message_id": message_id}


@router.post("/sessions/{session_id}/abort")
async def abort_session(session_id: str):
    """Abort a running session's LLM stream."""
    service = get_agent_service()
    aborted = service.abort_session(session_id)
    return {"aborted": aborted, "session_id": session_id}


@router.get("/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Get session status: idle or busy."""
    service = get_agent_service()
    status = service.get_session_status(session_id)
    return {"session_id": session_id, "status": status}
