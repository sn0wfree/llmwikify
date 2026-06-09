"""Agent Backend Routes - Quick Research API endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse

from llmwikify.apps.chat.db import ChatDatabase
from llmwikify.apps.research.config import merge_research_config
from llmwikify.apps.research.engine import ResearchEngine
from llmwikify.apps.research.task_manager import get_task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

# These are set during app startup
_AGENT_DB: ChatDatabase | None = None
_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_RESEARCH_CONFIG: dict[str, Any] | None = None


def set_research_deps(db: ChatDatabase, wiki_registry: Any, llm_client: Any, config: dict[str, Any] | None = None) -> None:
    global _AGENT_DB, _WIKI_REGISTRY, _LLM_CLIENT, _RESEARCH_CONFIG
    _AGENT_DB = db
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _RESEARCH_CONFIG = config


def _get_db() -> ChatDatabase:
    if _AGENT_DB is None:
        raise RuntimeError("Research deps not initialized")
    return _AGENT_DB


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    try:
        if wiki_id:
            return _WIKI_REGISTRY.get_wiki(wiki_id)
        return _WIKI_REGISTRY.get_default_wiki()
    except (ValueError, KeyError) as e:
        raise ValueError(f"No wiki available: {e}. Configure a wiki in ~/.llmwikify/llmwikify.json or pass wiki_id.") from e


def _get_engine(wiki_id: str | None = None) -> ResearchEngine:
    db = _get_db()
    wiki = _get_wiki(wiki_id)
    llm = _LLM_CLIENT
    if llm is None:
        from llmwikify.apps.chat.agent.agent_service import AgentService  # noqa: F401
        from .chat_sse import get_agent_service
        svc = get_agent_service()
        llm = svc._get_llm()
    return ResearchEngine(wiki=wiki, db=db, llm_client=llm, config=_RESEARCH_CONFIG)


# ─── SSE Streaming Endpoint ────────────────────────────────────────

@router.get("/{research_id}/stream")
async def stream_research(research_id: str):
    """SSE stream of research events for a session.

    Reads from the background task's event queue. Safe to connect at any time
    (before, during, or after the task runs). Events are buffered per-session.
    """
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    tm = get_task_manager()

    async def event_generator():
        try:
            async for event in tm.get_event_stream(research_id):
                yield {"event": "message", "data": json.dumps(event)}
        except GeneratorExit:
            logger.info("Client disconnected from research stream %s", research_id)
        except Exception as e:
            logger.error("Research stream error for session %s: %s", research_id, e)

    return EventSourceResponse(event_generator())


# ─── Start / Resume ────────────────────────────────────────────────

@router.post("/start")
async def start_research(request: Request):
    """Start a deep research session as a background task.

    Body: { "query": str, "wiki_id"?: str }

    Returns { session_id, status } immediately. Subscribe to
    GET /api/research/{id}/stream for live SSE events.
    """
    body = await request.json()
    query = body.get("query", "").strip()
    wiki_id = body.get("wiki_id")

    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    try:
        engine = _get_engine(wiki_id)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Create session
    session_id = engine.session_manager.create_session(query, wiki_id or "default")

    # Launch background task
    tm = get_task_manager()
    tm.start(session_id, query, engine, resume=False)

    return {"session_id": session_id, "status": "running"}


@router.post("/{research_id}/resume")
async def resume_research(research_id: str):
    """Resume a paused research session as a background task.

    Returns { session_id, status } immediately. Subscribe to
    GET /api/research/{id}/stream for live SSE events.
    """
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    if session["status"] not in ("paused", "pausing", "gathering", "planning", "analyzing", "synthesizing", "report", "reviewing"):
        return JSONResponse({"error": f"Cannot resume session in status: {session['status']}"}, status_code=400)

    engine = _get_engine(session.get("wiki_id"))

    tm = get_task_manager()
    tm.start(research_id, session["query"], engine, resume=True)

    return {"session_id": research_id, "status": "running"}


# ─── Read-only Endpoints ───────────────────────────────────────────

@router.get("/")
async def list_research(wiki_id: str | None = None):
    """List all research sessions."""
    db = _get_db()
    sessions = db.list_research_sessions(wiki_id)
    return {"research_sessions": sessions}


@router.get("/{research_id}")
async def get_research(research_id: str):
    """Get research session details including sub-queries and sources."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    session["sub_queries"] = db.get_sub_queries(research_id)
    session["sources"] = db.get_sources(research_id)
    session["sub_query_count"] = len(session["sub_queries"])
    session["source_count"] = len(session["sources"])
    return session


@router.get("/{research_id}/sources")
async def get_research_sources(research_id: str):
    """Get sources gathered for a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    sources = db.get_sources(research_id)
    return {"sources": sources}


@router.get("/{research_id}/sub-queries")
async def get_research_sub_queries(research_id: str):
    """Get sub-queries for a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    sub_queries = db.get_sub_queries(research_id)
    return {"sub_queries": sub_queries}


# ─── Control Endpoints ─────────────────────────────────────────────

@router.post("/{research_id}/pause")
async def pause_research(research_id: str):
    """Pause a running research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    if session["status"] not in ("planning", "gathering", "analyzing", "synthesizing", "report", "reviewing"):
        return JSONResponse({"error": f"Cannot pause session in status: {session['status']}"}, status_code=400)

    db.update_research_status(research_id, "pausing", session.get("current_step"))

    # Also cancel the background task if running
    tm = get_task_manager()
    tm.cancel(research_id)

    return {"paused": True, "research_id": research_id}


@router.delete("/{research_id}")
async def cancel_research(research_id: str):
    """Cancel or delete a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    # Cancel background task if running
    tm = get_task_manager()
    tm.cancel(research_id)

    # For done/cancelled/error sessions, delete entirely
    if session["status"] in ("done", "cancelled", "error"):
        deleted = db.delete_research(research_id)
        return {"cancelled": deleted, "research_id": research_id}

    # For running sessions, set cancelling status
    db.update_research_status(research_id, "cancelling", session.get("current_step"))
    return {"cancelled": True, "research_id": research_id}


# ─── Save to Wiki ──────────────────────────────────────────────────

@router.post("/{research_id}/save-to-wiki")
async def save_to_wiki(research_id: str, request: Request):
    """Save research results to wiki via confirmation flow."""
    body = await request.json()
    page_name = body.get("page_name")

    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    if session["status"] != "done":
        return JSONResponse({"error": "Session not done yet"}, status_code=400)
    if session.get("wiki_page_name"):
        return JSONResponse({"error": f"Already saved to wiki as: {session['wiki_page_name']}"}, status_code=409)

    try:
        from llmwikify.apps.chat.agent.agent_service import AgentService  # noqa: F401
        from .chat_sse import get_agent_service
        svc = get_agent_service()
        wiki_id = session.get("wiki_id")
        registry = svc._get_tool_registry(wiki_id)
    except Exception as e:
        return JSONResponse({"error": f"Cannot access tool registry: {e}"}, status_code=500)

    result = await registry.execute("research_save_to_wiki", {
        "session_id": research_id,
        "page_name": page_name,
        "include_sources": body.get("include_sources", True),
    })

    return result


@router.post("/{research_id}/rate")
async def rate_research(research_id: str, request: Request):
    """Rate sources from a research session."""
    body = await request.json()
    rating = body.get("rating", 0)
    source_ratings = body.get("source_ratings", {})
    feedback = body.get("feedback")

    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    for source_id, source_rating in source_ratings.items():
        try:
            db.rate_source(source_id, int(source_rating))
        except Exception as e:
            logger.warning("Failed to rate source %s: %s", source_id, e)

    return {"rated": True, "research_id": research_id, "rating": rating, "feedback": feedback}
