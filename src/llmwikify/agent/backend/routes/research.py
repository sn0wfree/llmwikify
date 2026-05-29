"""Agent Backend Routes - Deep Research API endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse

from ..db import AgentDatabase
from ..research.config import merge_research_config
from ..research.engine import ResearchEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

# These are set during app startup
_AGENT_DB: AgentDatabase | None = None
_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_RESEARCH_CONFIG: dict[str, Any] | None = None


def set_research_deps(db: AgentDatabase, wiki_registry: Any, llm_client: Any, config: dict[str, Any] | None = None) -> None:
    global _AGENT_DB, _WIKI_REGISTRY, _LLM_CLIENT, _RESEARCH_CONFIG
    _AGENT_DB = db
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _RESEARCH_CONFIG = config


def _get_db() -> AgentDatabase:
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
        from ..service import AgentService
        # Get LLM from agent service (lazy init)
        from .agent import get_agent_service
        svc = get_agent_service()
        llm = svc._get_llm()
    return ResearchEngine(wiki=wiki, db=db, llm_client=llm, config=_RESEARCH_CONFIG)


@router.post("/start")
async def start_research(request: Request):
    """Start a deep research session with SSE progress.

    Body: { "query": str, "wiki_id"?: str }
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

    db = _get_db()
    wiki = _get_wiki(wiki_id)

    # Create session
    session_id = engine.session_manager.create_session(query, wiki_id or "default")

    async def event_generator():
        try:
            async for event in engine.run(session_id, query):
                yield {"event": "message", "data": json.dumps(event)}
        except GeneratorExit:
            logger.info("Client disconnected from research stream %s", session_id)
        except Exception as e:
            logger.error("Research engine error for session %s: %s", session_id, e)
            yield {"event": "message", "data": json.dumps({"type": "error", "error": str(e)})}

    return EventSourceResponse(event_generator())


@router.get("/")
async def list_research(wiki_id: str | None = None):
    """List all research sessions."""
    db = _get_db()
    sessions = db.list_research_sessions(wiki_id)
    # sub_query_count and source_count are now included from batch query
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
    return session


@router.post("/{research_id}/pause")
async def pause_research(research_id: str):
    """Pause a running research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    if session["status"] not in ("planning", "gathering", "analyzing", "synthesizing", "report", "reviewing"):
        return JSONResponse({"error": f"Cannot pause session in status: {session['status']}"}, status_code=400)

    # Set "pausing" status — engine will pick it up on next control signal check
    db.update_research_status(research_id, "pausing", session.get("current_step"))
    return {"paused": True, "research_id": research_id}


@router.post("/{research_id}/resume")
async def resume_research(research_id: str):
    """Resume a paused research session (restarts from current step)."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    if session["status"] not in ("paused", "pausing", "gathering", "planning", "analyzing", "synthesizing", "report", "reviewing"):
        return JSONResponse({"error": f"Cannot resume session in status: {session['status']}"}, status_code=400)

    engine = _get_engine(session.get("wiki_id"))

    async def event_generator():
        try:
            async for event in engine.run(research_id, session["query"], resume=True):
                yield {"event": "message", "data": json.dumps(event)}
        except GeneratorExit:
            logger.info("Client disconnected from research resume stream %s", research_id)
        except Exception as e:
            logger.error("Research resume error for session %s: %s", research_id, e)
            yield {"event": "message", "data": json.dumps({"type": "error", "error": str(e)})}

    return EventSourceResponse(event_generator())


@router.delete("/{research_id}")
async def cancel_research(research_id: str):
    """Cancel or delete a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    # For done/cancelled/error sessions, delete entirely
    if session["status"] in ("done", "cancelled", "error"):
        deleted = db.delete_research(research_id)
        return {"cancelled": deleted, "research_id": research_id}

    # For running sessions, set cancelling status
    db.update_research_status(research_id, "cancelling", session.get("current_step"))
    return {"cancelled": True, "research_id": research_id}


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

    # Get tool registry from agent service
    try:
        from ..service import AgentService
        from .agent import get_agent_service
        svc = get_agent_service()
        wiki_id = session.get("wiki_id")
        registry = svc._get_tool_registry(wiki_id)
    except Exception as e:
        return JSONResponse({"error": f"Cannot access tool registry: {e}"}, status_code=500)

    # Execute tool — creates confirmation since requires_confirmation="pre"
    result = await registry.execute("research_save_to_wiki", {
        "session_id": research_id,
        "page_name": page_name,
    })

    return result


@router.get("/{research_id}/sources")
async def get_research_sources(research_id: str):
    """Get sources gathered for a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    sources = db.get_sources(research_id)
    return {"sources": sources}


@router.post("/{research_id}/rate")
async def rate_research(research_id: str, request: Request):
    """Rate sources from a research session.

    Body: { "rating": int (1-5), "source_ratings": { "source_id": int }?, "feedback": str? }
    """
    body = await request.json()
    rating = body.get("rating", 0)
    source_ratings = body.get("source_ratings", {})
    feedback = body.get("feedback")

    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    # Rate individual sources
    for source_id, source_rating in source_ratings.items():
        try:
            db.rate_source(source_id, int(source_rating))
        except Exception as e:
            logger.warning("Failed to rate source %s: %s", source_id, e)

    return {"rated": True, "research_id": research_id, "rating": rating, "feedback": feedback}


@router.get("/{research_id}/sub-queries")
async def get_research_sub_queries(research_id: str):
    """Get sub-queries for a research session."""
    db = _get_db()
    session = db.get_research_session(research_id)
    if not session:
        return JSONResponse({"error": "Research session not found"}, status_code=404)

    sub_queries = db.get_sub_queries(research_id)
    return {"sub_queries": sub_queries}
