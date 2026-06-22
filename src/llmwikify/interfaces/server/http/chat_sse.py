"""Agent Backend Routes - Agent chat API with SSE support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.apps.chat.bus.adapter import BusAdapter
from llmwikify.interfaces.server.http._models import (
    ApplyProposalsRequest,
    ApprovalRequest,
    BatchApproveProposalsRequest,
    BatchApproveRequest,
    ChatRequest,
    CreateSessionRequest,
    SaveConfigRequest,
)

logger = logging.getLogger(__name__)

# Phase 4.4 (v0.36): SSE heartbeat and timeout configuration.
# HEARTBEAT_INTERVAL: seconds between keepalive pings (15s).
# STREAM_TIMEOUT: total stream lifetime in seconds (300s = 5min).
HEARTBEAT_INTERVAL = 15
STREAM_TIMEOUT = 300

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
    req = ChatRequest(**body)
    jwt_token = get_jwt_from_request(request)
    service = get_agent_service()

    # Phase 19-A: bus adapter for SSE→bus mirror. The adapter is a
    # stateless wrapper around MessageBus + the SSE→WS translator;
    # see apps/chat/bus/adapter.py. Default bus is the process-wide
    # singleton, so the WS handler sees the same outbound stream.
    bus_adapter = BusAdapter()

    async def event_generator():
        """SSE generator with heartbeat and timeout (Phase 4.4 / v0.36).

        Sends a heartbeat comment every 15s to keep the
        connection alive through proxies/CDNs. Total stream
        lifetime is capped at 5 minutes (300s).

        Phase 19-A: each yielded event is mirrored to the in-process
        ``MessageBus`` so WebSocket subscribers and any future channel
        consumer can fan-out without coupling to ``ChatOrchestrator``.
        The SSE wire format is unchanged; mirroring is a side-effect.
        """
        start_time = time.monotonic()
        last_event_time = start_time
        async for event in service.chat(
            message=req.message,
            session_id=req.session_id,
            wiki_id=req.wiki_id,
            jwt_token=jwt_token,
        ):
            # Mirror to bus (target_id empty = fan-out to any consumer;
            # WS handler will filter by its own chat_id subscription).
            bus_adapter.mirror_sse_event(
                event,
                target_id="",
                session_key=(
                    f"http:{req.session_id}" if req.session_id else ""
                ),
            )
            yield {
                "event": "message",
                "data": json.dumps(event),
            }
            last_event_time = time.monotonic()
            # Check total timeout
            if last_event_time - start_time > STREAM_TIMEOUT:
                timeout_event = {
                    "type": "timeout",
                    "message": "Stream timed out after 5 minutes",
                }
                bus_adapter.mirror_sse_event(
                    timeout_event,
                    target_id="",
                    session_key=(
                        f"http:{req.session_id}" if req.session_id else ""
                    ),
                )
                yield {
                    "event": "message",
                    "data": json.dumps(timeout_event),
                }
                return
        # Final heartbeat check
        elapsed = time.monotonic() - start_time
        if elapsed > HEARTBEAT_INTERVAL:
            yield {"event": "heartbeat", "data": ""}

    return EventSourceResponse(
        event_generator(),
        ping=HEARTBEAT_INTERVAL,
    )


@router.get("/sessions")
async def list_sessions():
    service = get_agent_service()
    sessions = service.db.list_chat_sessions()
    return {"sessions": sessions}


@router.post("/sessions")
async def create_session(request: Request):
    body = await request.json()
    req = CreateSessionRequest(**body)
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
    body = await request.json()
    message_id = body.get("message_id", "")
    if not message_id:
        return {"error": "message_id is required"}
    service = get_agent_service()
    count = service.revert_session(session_id, message_id)
    return {"reverted": count, "session_id": session_id}


@router.put("/sessions/{session_id}/messages/{message_id}")
async def edit_message(session_id: str, message_id: str, request: Request):
    """Edit a user message's content in-place."""
    body = await request.json()
    new_content = body.get("content", "")
    if not new_content:
        return {"error": "content is required"}
    service = get_agent_service()
    ok = service.edit_message(message_id, new_content)
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
async def batch_approve_proposals(request: Request):
    body = await request.json()
    req = BatchApproveProposalsRequest(**body)
    service = get_agent_service()
    return service.batch_approve_proposals(req.ids)


@router.post("/dream/proposals/apply")
async def apply_proposals(request: Request):
    body = await request.json()
    req = ApplyProposalsRequest(**body)
    service = get_agent_service()
    return await service.apply_proposals(req.wiki_id, req.ids)


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
    try:
        return service.get_agent_status(wiki_id)
    except (KeyError, ValueError):
        return {
            "state": "idle",
            "scheduler_tasks": [],
            "pending_work": {},
            "action_log": [],
            "pending_confirmations": 0,
            "dream_proposals": {},
            "unread_notifications": 0,
        }


# --- Research run endpoints ---

@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: str):
    service = get_agent_service()
    return service.get_research_run_status(run_id)


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
async def approve_and_continue(confirmation_id: str, request: Request):
    """Approve confirmation, execute tool, and stream LLM follow-up."""
    body = await request.json()
    req = ApprovalRequest(**body)
    service = get_agent_service()

    bus_adapter = BusAdapter()

    async def event_generator():
        """SSE generator with heartbeat and timeout (Phase 4.4 / v0.36).

        Phase 19-A: mirrors each event to MessageBus for fan-out.
        """
        start_time = time.monotonic()
        async for event in service.approve_confirmation_and_continue(
            confirmation_id=confirmation_id,
            session_id=req.session_id,
            wiki_id=req.wiki_id,
            arguments=req.arguments,
        ):
            bus_adapter.mirror_sse_event(
                event,
                target_id="",
                session_key=(
                    f"http:{req.session_id}" if req.session_id else ""
                ),
            )
            yield {"event": "message", "data": json.dumps(event)}
            elapsed = time.monotonic() - start_time
            if elapsed > STREAM_TIMEOUT:
                timeout_event = {
                    "type": "timeout",
                    "message": "Stream timed out after 5 minutes",
                }
                bus_adapter.mirror_sse_event(
                    timeout_event,
                    target_id="",
                    session_key=(
                        f"http:{req.session_id}" if req.session_id else ""
                    ),
                )
                yield {
                    "event": "message",
                    "data": json.dumps(timeout_event),
                }
                return

    return EventSourceResponse(
        event_generator(),
        ping=HEARTBEAT_INTERVAL,
    )


@router.delete("/confirmations/{confirmation_id}")
async def reject_confirmation(confirmation_id: str, request: Request):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.reject_confirmation(confirmation_id, wiki_id)


@router.post("/confirmations/batch")
async def batch_approve(request: Request):
    body = await request.json()
    req = BatchApproveRequest(**body)
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.batch_approve_confirmations(req.ids, wiki_id)


# --- Config endpoints ---

@router.get("/config")
async def get_llm_config():
    from llmwikify.apps.chat.config_manager import get_global_config_manager
    manager = get_global_config_manager()
    llm_cfg = manager.load_effective_llm_config()
    result = manager.mask_api_key(llm_cfg)
    # v0.40: include custom system prompt from user preferences
    try:
        service = get_agent_service()
        if service.memory_manager:
            prefs = await service.memory_manager.preferences.aall("default")
            result["system_prompt"] = prefs.get("system_prompt", "")
    except Exception:
        result["system_prompt"] = ""
    return result


@router.put("/config")
async def save_llm_config(request: Request):
    from llmwikify.apps.chat.config_manager import get_global_config_manager
    body = await request.json()
    req = SaveConfigRequest(**body)
    manager = get_global_config_manager()
    # Preserve real api_key: if the incoming key is masked (contains ***),
    # keep the original value from the existing config.
    config_dict = req.model_dump(exclude_none=True)
    incoming_key = config_dict.get("api_key", "")
    if incoming_key and "***" in incoming_key:
        current = manager.load_effective_llm_config()
        config_dict["api_key"] = current.get("api_key", incoming_key)
    # v0.40: system_prompt is stored in user preferences, not LLM config
    system_prompt = config_dict.pop("system_prompt", None)
    manager.save_global_config(config_dict)
    manager.reload()
    if system_prompt is not None:
        try:
            service = get_agent_service()
            if service.memory_manager:
                await service.memory_manager.preferences.aset(
                    "default", "system_prompt", system_prompt,
                )
        except Exception as e:
            logger.warning("Failed to save system prompt: %s", e)
    return {"saved": True}


@router.post("/config/reload")
async def reload_llm_config():
    from llmwikify.apps.chat.config_manager import get_global_config_manager
    manager = get_global_config_manager()
    manager.reload()
    return {"reloaded": True}


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
