"""Agent Backend Routes - PPT Generator API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db import AgentDatabase
from ..ppt.engine import PPTEngine
from ..ppt.schema import (
    FromChatRequest,
    FromResearchRequest,
    GenerateRequest,
    OutlineRequest,
)
from ..ppt.themes import list_themes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ppt", tags=["ppt"])

# These are set during app startup
_AGENT_DB: AgentDatabase | None = None
_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_PPT_CONFIG: dict[str, Any] | None = None


def set_ppt_deps(db: AgentDatabase, wiki_registry: Any, llm_client: Any, config: dict[str, Any] | None = None) -> None:
    global _AGENT_DB, _WIKI_REGISTRY, _LLM_CLIENT, _PPT_CONFIG
    _AGENT_DB = db
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _PPT_CONFIG = config


def _get_db() -> AgentDatabase:
    if _AGENT_DB is None:
        raise RuntimeError("PPT deps not initialized")
    return _AGENT_DB


def _get_llm() -> Any:
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT
    # Fallback: try to get from agent service
    try:
        from .agent import get_agent_service
        svc = get_agent_service()
        return svc._get_llm()
    except (ImportError, RuntimeError) as e:
        raise RuntimeError(f"LLM client not available: {e}")


def _get_engine() -> PPTEngine:
    llm = _get_llm()
    return PPTEngine(llm=llm)


# ─── Outline Generation ───────────────────────────────────────────────

@router.post("/outline")
async def generate_outline(request: OutlineRequest):
    """Generate presentation outline (Step 1)."""
    try:
        engine = _get_engine()
        response = await engine.generate_outline(request)
        return response.model_dump()
    except Exception as e:
        logger.error(f"Outline generation failed: {e}", exc_info=True)
        return JSONResponse(
            {"error": f"Outline generation failed: {str(e)}"},
            status_code=500,
        )


# ─── Content Generation ───────────────────────────────────────────────

@router.post("/generate")
async def generate_presentation(request: GenerateRequest):
    """Generate presentation content based on outline (Step 2)."""
    try:
        engine = _get_engine()
        response = await engine.generate_content(request)
        return response.model_dump()
    except Exception as e:
        logger.error(f"PPT generation failed: {e}", exc_info=True)
        return JSONResponse(
            {"error": f"PPT generation failed: {str(e)}"},
            status_code=500,
        )


# ─── From Research ────────────────────────────────────────────────────

@router.post("/from-research")
async def generate_from_research(request: FromResearchRequest):
    """Generate outline from Quick Research results."""
    try:
        db = _get_db()
        
        # Get research session
        session = db.get_research_session(request.research_id)
        if not session:
            return JSONResponse(
                {"error": "Research session not found"},
                status_code=404,
            )
        
        # Extract content from research result
        result = session.get("result", "")
        topic = session.get("query", "Research Results")
        
        # Parse research result to extract key findings
        findings = []
        if isinstance(result, dict):
            findings = result.get("findings", [])
            summary = result.get("summary", str(result)[:500])
        else:
            summary = str(result)[:500]
        
        # Get source count
        sources = db.get_sources(request.research_id)
        source_count = len(sources) if sources else 0
        
        engine = _get_engine()
        outline = await engine.generate_from_research(
            topic=topic,
            summary=summary,
            findings=findings,
            source_count=source_count,
        )
        
        return {
            "outline": outline.model_dump(),
            "source_summary": summary[:200],
            "source_count": source_count,
        }
    except Exception as e:
        logger.error(f"Research to PPT failed: {e}", exc_info=True)
        return JSONResponse(
            {"error": f"Research to PPT failed: {str(e)}"},
            status_code=500,
        )


# ─── From Chat ────────────────────────────────────────────────────────

@router.post("/from-chat")
async def generate_from_chat(request: FromChatRequest):
    """Generate outline from Chat conversation."""
    try:
        db = _get_db()
        
        # Get chat session
        session = db.get_session(request.chat_session_id)
        if not session:
            return JSONResponse(
                {"error": "Chat session not found"},
                status_code=404,
            )
        
        # Get messages from chat
        messages = db.get_messages(request.chat_session_id)
        if not messages:
            return JSONResponse(
                {"error": "No messages in chat session"},
                status_code=400,
            )
        
        # Extract content from messages
        topic = session.get("title", "Chat Conversation")
        message_count = len(messages)
        
        # Build summary from messages
        key_points = []
        summary_parts = []
        for msg in messages[-10:]:  # Last 10 messages
            content = msg.get("content", "")
            if content:
                summary_parts.append(content[:200])
                if len(content) > 50:
                    key_points.append(content[:100])
        
        summary = "\n".join(summary_parts[:5])
        key_points = key_points[:5]
        
        engine = _get_engine()
        outline = await engine.generate_from_chat(
            topic=topic,
            summary=summary,
            key_points=key_points,
            message_count=message_count,
        )
        
        return {
            "outline": outline.model_dump(),
            "source_summary": summary[:200],
            "source_count": message_count,
        }
    except Exception as e:
        logger.error(f"Chat to PPT failed: {e}", exc_info=True)
        return JSONResponse(
            {"error": f"Chat to PPT failed: {str(e)}"},
            status_code=500,
        )


# ─── Themes ───────────────────────────────────────────────────────────

@router.get("/themes")
async def get_themes():
    """Get list of available themes."""
    themes = list_themes()
    return {"themes": [t.model_dump() for t in themes]}
