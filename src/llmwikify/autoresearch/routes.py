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

from llmwikify.autoresearch.config import merge_six_step_config
from llmwikify.autoresearch.db import AutoResearchDatabase
from llmwikify.autoresearch.engine import ResearchEngine
from llmwikify.autoresearch.task_manager import get_task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoresearch", tags=["autoresearch"])

# Initialized at app startup
_AUTORESEARCH_DB: AutoResearchDatabase | None = None
_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_AUTORESEARCH_CONFIG: dict[str, Any] | None = None


def set_autoresearch_deps(
    db: AutoResearchDatabase,
    wiki_registry: Any,
    llm_client: Any,
    config: dict[str, Any] | None = None,
) -> None:
    """Wire up shared deps. Called from server startup."""
    global _AUTORESEARCH_DB, _WIKI_REGISTRY, _LLM_CLIENT, _AUTORESEARCH_CONFIG
    _AUTORESEARCH_DB = db
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _AUTORESEARCH_CONFIG = config


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


def _get_engine(wiki_id: str | None = None) -> ResearchEngine:
    db = _get_db()
    wiki = _get_wiki(wiki_id)
    llm = _LLM_CLIENT
    if llm is None:
        from llmwikify.agent.backend.routes.agent import get_agent_service
        svc = get_agent_service()
        llm = svc._get_llm()
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
    if session["status"] not in ("paused", "pausing", "gathering", "planning", "analyzing", "synthesizing", "report", "reviewing", "clarifying"):
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
