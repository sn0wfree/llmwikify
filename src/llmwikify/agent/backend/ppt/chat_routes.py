"""PPTChat Routes - SSE streaming for interactive slide editing."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from ..db import AgentDatabase
from .chat_router import PPTChatRouter
from .schema import Presentation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ppt/chat", tags=["ppt-chat"])

_AGENT_DB: AgentDatabase | None = None
_ROUTER: PPTChatRouter | None = None
_LLM_CLIENT: Any = None


def set_ppt_chat_deps(db: AgentDatabase, llm_client: Any = None) -> None:
    """Initialize PPTChat dependencies (called at app startup)."""
    global _AGENT_DB, _ROUTER, _LLM_CLIENT
    _AGENT_DB = db
    _LLM_CLIENT = llm_client


def _get_llm() -> Any:
    """Get LLM client, falling back to agent service."""
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT
    try:
        from ..routes.agent import get_agent_service
        svc = get_agent_service()
        return svc._get_llm()
    except (ImportError, RuntimeError) as e:
        raise RuntimeError(f"LLM client not available for PPTChat: {e}")


def _get_router() -> PPTChatRouter:
    """Get or create the PPTChat router."""
    global _ROUTER
    if _ROUTER is None:
        llm = _get_llm()
        _ROUTER = PPTChatRouter(llm=llm)
    return _ROUTER


@router.post("")
async def ppt_chat(request: Request):
    """PPT chat endpoint with SSE streaming.

    Request body:
      - message: str (user's natural language instruction)
      - task_id: str (PPT task to edit)
      - current_slide_index: int (which slide is focused, 0-indexed)
      - session_id: str (optional, for chat history continuity)

    SSE events:
      - session_created: {session_id}
      - thinking: {content} (LLM reasoning tokens)
      - message_delta: {content} (incremental response text)
      - tool_start: {tool, args} (deterministic tool started)
      - tool_end: {tool, result} (deterministic tool completed)
      - done: {updated_presentation, message}
      - error: {error}
    """
    body = await request.json()
    message = body.get("message", "")
    task_id = body.get("task_id")
    current_slide_index = body.get("current_slide_index", 0)
    session_id = body.get("session_id")

    if not task_id:
        return {"error": "task_id is required"}, 400

    if not db:
        return {"error": "PPTChat not initialized"}, 500

    try:
        chat_router = _get_router()
    except RuntimeError as e:
        return {"error": str(e)}, 500

    # Load presentation from task
    task = db.get_ppt_task(task_id)
    if not task:
        return {"error": "Task not found"}, 404

    presentation_data = task.get("presentation_json")
    if not presentation_data:
        return {"error": "Task has no presentation yet"}, 400

    # Parse presentation
    pres_dict = (
        json.loads(presentation_data)
        if isinstance(presentation_data, str)
        else presentation_data
    )
    if "presentation" in pres_dict:
        pres_dict = pres_dict["presentation"]
    try:
        presentation = Presentation(**pres_dict)
    except Exception as e:
        logger.error(f"Failed to parse presentation: {e}")
        return {"error": f"Invalid presentation data: {e}"}, 500

    # Create/get chat session
    if not session_id:
        session_id = db.create_ppt_chat_session(task_id)

    # Load chat history
    history = db.get_ppt_chat_messages(session_id, limit=10)

    # Save user message
    db.save_ppt_chat_message(session_id, "user", message)

    async def event_generator():
        # Yield session_created
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "session_created", "session_id": session_id}
            ),
        }

        full_response = ""
        async for event in chat_router.route(
            message=message,
            presentation=presentation,
            current_slide_index=current_slide_index,
            history=history,
        ):
            yield {
                "event": "message",
                "data": json.dumps(event, ensure_ascii=False),
            }

            if event.get("type") == "message_delta":
                full_response += event.get("content", "")

            if event.get("type") == "done":
                # Save assistant message
                msg = event.get("message", full_response)
                db.save_ppt_chat_message(session_id, "assistant", msg)

                # Update task presentation if changed
                updated = event.get("updated_presentation")
                if updated:
                    updated_slides = updated.get("slides", [])
                    db.set_ppt_task_partial_presentation(
                        task_id, updated_slides
                    )

    return EventSourceResponse(event_generator())


@router.post("/sessions")
async def create_session(request: Request):
    """Create a PPTChat session."""
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        return {"error": "task_id required"}, 400
    session_id = _AGENT_DB.create_ppt_chat_session(task_id)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 50):
    """Get chat history for a PPTChat session."""
    messages = _AGENT_DB.get_ppt_chat_messages(session_id, limit=limit)
    return {"messages": messages, "session_id": session_id}
