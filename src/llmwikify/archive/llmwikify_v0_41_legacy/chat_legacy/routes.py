"""AutoResearch HTTP routes.

Independent FastAPI router under /api/autoresearch/*. Mirrors the base
research API but with a separate prefix, so both can run simultaneously.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request

from llmwikify.apps.chat.config import merge_six_step_config
from llmwikify.apps.chat.db import AutoResearchDatabase
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine import ResearchEngine
from llmwikify.apps.chat.task_manager import get_task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoresearch", tags=["autoresearch"])

# Initialized at app startup
_AUTORESEARCH_DB: AutoResearchDatabase | None = None
_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_AUTORESEARCH_CONFIG: dict[str, Any] | None = None


_TOOL_REGISTRY: Any = None


def set_autoresearch_deps(
    db: AutoResearchDatabase,
    wiki_registry: Any,
    llm_client: Any,
    config: dict[str, Any] | None = None,
    tool_registry: Any = None,
) -> None:
    """Wire up shared deps. Called from server startup."""
    global _AUTORESEARCH_DB, _WIKI_REGISTRY, _LLM_CLIENT, _AUTORESEARCH_CONFIG, _TOOL_REGISTRY
    _AUTORESEARCH_DB = db
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _AUTORESEARCH_CONFIG = config
    _TOOL_REGISTRY = tool_registry


def _get_db() -> AutoResearchDatabase:
    if _AUTORESEARCH_DB is None:
        raise RuntimeError("AutoResearch deps not initialized")
    return _AUTORESEARCH_DB


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    try:
        if wiki_id:
            return _WIKI_REGISTRY.get_wiki(wiki_id)
        return _WIKI_REGISTRY.get_default_wiki()
    except (ValueError, KeyError) as e:
        raise ValueError(f"No wiki available: {e}. Configure a wiki in ~/.llmwikify/llmwikify.json or pass wiki_id.") from e


def _get_tool_registry(wiki_id: str | None = None) -> Any:
    """Phase 4.5 (v0.36): get tool registry for a wiki.

    The tool registry is injected via set_autoresearch_deps.
    When not available, falls back to the wiki registry's
    get_tool_registry method.
    """
    if _TOOL_REGISTRY is not None:
        return _TOOL_REGISTRY
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    return _WIKI_REGISTRY.get_tool_registry(wiki_id)


def _get_engine(wiki_id: str | None = None) -> ResearchEngine:
    db = _get_db()
    wiki = _get_wiki(wiki_id)
    llm = _LLM_CLIENT
    if llm is None:
        raise RuntimeError(
            "AutoResearch LLM client not initialized. "
            "Call set_autoresearch_deps(llm_client=...) at startup."
        )
    return ResearchEngine(
        wiki=wiki,
        db=db,
        llm_client=llm,
        config=_AUTORESEARCH_CONFIG,
    )


# ─── SSE Streaming ──────────────────────────────────────────────────


@router.get("/{session_id}/stream")
async def stream_autoresearch(session_id: str):
    """SSE stream of autoresearch events for a session.

    Events include 6-step framework events: clarification_complete,
    framework_compliance, structure_check, etc.
    """
    from sse_starlette import EventSourceResponse
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}

    async def event_gen():
        tm = get_task_manager()
        try:
            async for event in tm.get_event_stream(session_id):
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
        except asyncio.CancelledError:
            logger.info("Client disconnected from autoresearch stream %s", session_id)
            raise

    return EventSourceResponse(event_gen())


# ─── Start Session ──────────────────────────────────────────────────


@router.post("/start")
async def start_autoresearch(request: Request):
    """Start a new 6-step autoresearch session as a background task."""
    body = await request.json()
    query = body.get("query", "").strip()
    wiki_id = body.get("wiki_id")

    if not query:
        return {"error": "query is required"}

    engine = _get_engine(wiki_id)
    session_id = engine.session_manager.create_session(query, wiki_id or "default")
    tm = get_task_manager()
    tm.start(session_id, query, engine, resume=False)
    return {"session_id": session_id, "status": "running"}


@router.post("/{session_id}/resume")
async def resume_autoresearch(session_id: str):
    """Resume a paused or interrupted session."""
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    if session["status"] not in ("paused", "pausing", "gathering", "planning", "analyzing", "synthesizing", "report", "reviewing", "clarifying", "incomplete", "error", "timeout", "done"):
        return {"error": f"Cannot resume from status: {session['status']}"}

    engine = _get_engine(session.get("wiki_id"))
    tm = get_task_manager()
    tm.start(session_id, session["query"], engine, resume=True)
    return {"session_id": session_id, "status": "running"}


# ─── List / Get ──────────────────────────────────────────────────────


@router.get("/list")
async def list_autoresearch(wiki_id: str | None = None):
    """List all autoresearch sessions."""
    db = _get_db()
    sessions = db.list_research_sessions(wiki_id)
    return {"autoresearch_sessions": sessions}


@router.get("/{session_id}")
async def get_autoresearch(session_id: str):
    """Get full session details, including 6-step fields."""
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    session["sub_queries"] = db.get_sub_queries(session_id)
    session["sources"] = db.get_sources(session_id)
    return session


# ─── 6-step framework specific endpoints ────────────────────────────


@router.get("/{session_id}/clarification")
async def get_clarification(session_id: str):
    """Get the concept-clarification result for a session."""
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    raw = session.get("clarification_json")
    if not raw:
        return {"clarification": None}
    try:
        return {"clarification": json.loads(raw)}
    except (json.JSONDecodeError, TypeError):
        return {"clarification": None, "raw": raw}


@router.get("/{session_id}/events")
async def get_events(session_id: str):
    """Get the persisted event log for a session.

    Returns the full history of events emitted by the engine (typed
    messages from the SSE stream), in insertion order. Empty list for
    sessions that have no events yet (in-flight or pre-persistence).
    """
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found", "events": []}
    return {"events": db.get_events(session_id)}


# ─── Control: pause / cancel ────────────────────────────────────────


@router.post("/{session_id}/pause")
async def pause_autoresearch(session_id: str):
    """Pause a running session."""
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    if session["status"] not in ("planning", "gathering", "analyzing", "synthesizing", "report", "reviewing", "clarifying"):
        return {"error": f"Cannot pause from status: {session['status']}"}
    db.update_research_status(session_id, "pausing", session.get("current_step"))
    tm = get_task_manager()
    tm.cancel(session_id)
    return {"paused": True, "session_id": session_id}


@router.delete("/{session_id}")
async def cancel_autoresearch(session_id: str):
    """Cancel or delete a session."""
    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": f"Session {session_id} not found"}
    tm = get_task_manager()
    if session["status"] in ("done", "error", "timeout"):
        tm.cancel(session_id)
        deleted = db.delete_research(session_id)
        return {"cancelled": deleted, "session_id": session_id}
    db.update_research_status(session_id, "cancelling", session.get("current_step"))
    return {"cancelled": True, "session_id": session_id}


# ─── Save to Wiki ──────────────────────────────────────────────────


@router.post("/{session_id}/save-to-wiki")
async def save_to_wiki(session_id: str, request: Request):
    """Save research results to wiki via confirmation flow."""
    from fastapi.responses import JSONResponse

    body = await request.json()
    page_name = body.get("page_name")

    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    if session["status"] != "done":
        return JSONResponse({"error": "Session not done yet"}, status_code=400)
    if session.get("wiki_page_name"):
        return JSONResponse({"error": f"Already saved to wiki as: {session['wiki_page_name']}"}, status_code=409)

    try:
        wiki_id = session.get("wiki_id")
        registry = _get_tool_registry(wiki_id)
    except Exception as e:
        return JSONResponse({"error": f"Cannot access tool registry: {e}"}, status_code=500)

    result = await registry.execute("research_save_to_wiki", {
        "session_id": session_id,
        "page_name": page_name,
        "include_sources": body.get("include_sources", True),
    })

    return result


# ─── Rate Sources ──────────────────────────────────────────────────


@router.post("/{session_id}/rate")
async def rate_research(session_id: str, request: Request):
    """Rate sources from a research session."""
    body = await request.json()
    rating = body.get("rating", 0)
    source_ratings = body.get("source_ratings", {})
    feedback = body.get("feedback")

    db = _get_db()
    session = db.get_research_session(session_id)
    if not session:
        return {"error": "Session not found"}

    for source_id, source_rating in source_ratings.items():
        try:
            db.rate_source(source_id, int(source_rating))
        except Exception as e:
            logger.warning("Failed to rate source %s: %s", source_id, e)

    return {"rated": True, "session_id": session_id, "rating": rating, "feedback": feedback}
