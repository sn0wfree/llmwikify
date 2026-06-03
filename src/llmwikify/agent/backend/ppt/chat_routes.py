"""PPTChat Routes - SSE streaming for interactive slide editing."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette import EventSourceResponse

from ..db import AgentDatabase
from .chat_router import PPTChatRouter
from .schema import Presentation
from .themes import get_theme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ppt/chat", tags=["ppt-chat"])

_AGENT_DB: AgentDatabase | None = None
_ROUTER: PPTChatRouter | None = None
_LLM_CLIENT: Any = None

# ─── Confirmation state ────────────────────────────────────────

# session_id → {"presentation": Presentation, "task_id": str}
_PENDING_CHANGES: dict[str, dict] = {}

CONFIRMATION_KEYWORDS = {"确认", "执行", "apply", "confirm", "好的", "可以", "确认执行", "好的执行"}


def _is_confirmation(message: str) -> bool:
    """Check if a user message is a confirmation instruction."""
    msg = message.strip().lower()
    return msg in CONFIRMATION_KEYWORDS or msg.startswith(tuple(CONFIRMATION_KEYWORDS))


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
        raise HTTPException(status_code=400, detail="task_id is required")

    if not _AGENT_DB:
        raise HTTPException(status_code=500, detail="PPTChat not initialized")

    # ─── Confirmation handling ────────────────────────────────
    # If user sends a confirmation and there are pending changes, apply them
    if session_id and session_id in _pending_changes and _is_confirmation(message):
        pending = _pending_changes.pop(session_id)
        _AGENT_DB.save_ppt_chat_message(session_id, "user", message)
        _AGENT_DB.update_ppt_task_presentation(pending["task_id"], pending["presentation"])
        logger.info(
            "PPTChat confirmed: task=%s session=%s slides=%d",
            pending["task_id"], session_id,
            len(pending["presentation"].get("slides", [])),
        )

        async def confirm_generator():
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "session_created", "session_id": session_id}
                ),
            }
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "done",
                    "updated_presentation": pending["presentation"],
                    "message": "修改已应用",
                }),
            }

        return EventSourceResponse(confirm_generator())

    # ─── Normal flow ──────────────────────────────────────────

    try:
        chat_router = _get_router()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Load presentation from task
    task = _AGENT_DB.get_ppt_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    presentation_data = task.get("presentation_json")
    if not presentation_data:
        raise HTTPException(
            status_code=400, detail="Task has no presentation yet"
        )

    # Parse presentation (defensive: rebuild missing fields from task row)
    pres_dict = (
        json.loads(presentation_data)
        if isinstance(presentation_data, str)
        else presentation_data
    )
    if isinstance(pres_dict, dict) and "presentation" in pres_dict:
        pres_dict = pres_dict["presentation"]
    if not isinstance(pres_dict, dict):
        pres_dict = {"slides": []}
    # Defensive merge: ensure required Presentation fields are present
    # (handles partial-format corruption from older chat turns)
    pres_dict.setdefault("title", task.get("title") or "Untitled")
    pres_dict.setdefault("subtitle", task.get("subtitle") or "")
    pres_dict.setdefault(
        "source",
        {
            "type": task.get("source_type") or "topic",
            "id": task.get("source_id"),
        },
    )
    # Resolve theme to full Theme dict (with name, colors, etc.)
    # Handles: missing, empty, string, or incomplete dict (e.g. {"id": "x"})
    theme_val = pres_dict.get("theme")
    if isinstance(theme_val, str):
        theme_id = theme_val
    elif isinstance(theme_val, dict):
        theme_id = theme_val.get("id", task.get("theme", "minimal-white"))
    else:
        theme_id = task.get("theme", "minimal-white")
    try:
        full_theme = get_theme(theme_id).model_dump()
    except Exception:
        full_theme = {
            "id": theme_id, "name": theme_id,
            "colors": {"primary": "#3b82f6", "secondary": "#64748b",
                        "background": "#ffffff", "text": "#1e293b",
                        "accent": "#3b82f6"},
        }
    pres_dict["theme"] = full_theme
    pres_dict.setdefault("slides", [])

    try:
        presentation = Presentation(**pres_dict)
    except Exception as e:
        logger.error(
            "Failed to parse presentation for task %s: %s (pres_dict keys=%s)",
            task_id, e, list(pres_dict.keys()),
        )
        raise HTTPException(
            status_code=500, detail=f"Invalid presentation data: {e}"
        )

    # Create/get chat session
    if not session_id:
        session_id = _AGENT_DB.create_ppt_chat_session(task_id)

    # Load chat history
    history = _AGENT_DB.get_ppt_chat_messages(session_id, limit=10)

    # Save user message
    _AGENT_DB.save_ppt_chat_message(session_id, "user", message)

    logger.info(
        "PPTChat start: task=%s session=%s slide_idx=%d msg_len=%d slides=%d",
        task_id, session_id, current_slide_index, len(message),
        len(presentation.slides),
    )

    async def event_generator():
        # Yield session_created
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "session_created", "session_id": session_id}
            ),
        }

        full_response = ""
        has_tool_start = False  # Track if deterministic tool was used

        async for event in chat_router.route(
            message=message,
            presentation=presentation,
            current_slide_index=current_slide_index,
            history=history,
        ):
            if event.get("type") == "tool_start":
                has_tool_start = True

            yield {
                "event": "message",
                "data": json.dumps(event, ensure_ascii=False),
            }

            if event.get("type") == "message_delta":
                full_response += event.get("content", "")

            if event.get("type") == "done":
                # Save assistant message
                msg = event.get("message", full_response)
                _AGENT_DB.save_ppt_chat_message(session_id, "assistant", msg)

                # Update task presentation if changed
                updated = event.get("updated_presentation")
                if updated:
                    if has_tool_start:
                        # Deterministic tool → apply directly
                        _AGENT_DB.update_ppt_task_presentation(task_id, updated)
                        logger.info(
                            "PPTChat done (tool): task=%s session=%s slides=%d",
                            task_id, session_id, len(updated.get("slides", [])),
                        )
                    else:
                        # LLM modification → store as pending for confirmation
                        _pending_changes[session_id] = {
                            "presentation": updated,
                            "task_id": task_id,
                        }
                        logger.info(
                            "PPTChat pending confirmation: task=%s session=%s slides=%d",
                            task_id, session_id, len(updated.get("slides", [])),
                        )

    return EventSourceResponse(event_generator())


@router.post("/sessions")
async def create_session(request: Request):
    """Create a PPTChat session."""
    body = await request.json()
    task_id = body.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id required")
    session_id = _AGENT_DB.create_ppt_chat_session(task_id)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 50):
    """Get chat history for a PPTChat session."""
    messages = _AGENT_DB.get_ppt_chat_messages(session_id, limit=limit)
    return {"messages": messages, "session_id": session_id}
