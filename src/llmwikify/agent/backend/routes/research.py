"""Agent Backend Routes - Research API endpoints (Phase 4)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

RESEARCH_SERVICE: Any = None


def set_research_service(service: Any) -> None:
    global RESEARCH_SERVICE
    RESEARCH_SERVICE = service


def get_research_service() -> Any:
    if RESEARCH_SERVICE is None:
        raise RuntimeError("Research service not initialized")
    return RESEARCH_SERVICE


@router.post("/start")
async def start_research(request: Request):
    """Start a deep research session with SSE progress.

    Body: { "query": str, "wiki_id"?: str }
    """
    body = await request.json()
    query = body.get("query", "")
    wiki_id = body.get("wiki_id")

    async def event_generator():
        yield {"event": "message", "data": json.dumps({"type": "step", "step": "starting", "message": "Starting research..."})}
        yield {"event": "message", "data": json.dumps({"type": "done", "message": "Research not yet implemented"})}

    return EventSourceResponse(event_generator())


@router.get("/{research_id}")
async def get_research(research_id: str):
    """Get research session status."""
    return {"error": "Research not yet implemented"}


@router.get("/")
async def list_research():
    """List all research sessions."""
    return {"research_sessions": []}


@router.post("/{research_id}/pause")
async def pause_research(research_id: str):
    """Pause a running research session."""
    return {"error": "Research not yet implemented"}


@router.post("/{research_id}/resume")
async def resume_research(research_id: str):
    """Resume a paused research session."""
    return {"error": "Research not yet implemented"}


@router.delete("/{research_id}")
async def cancel_research(research_id: str):
    """Cancel a research session."""
    return {"cancelled": True}


@router.get("/{research_id}/sources")
async def get_research_sources(research_id: str):
    """Get sources gathered for a research session."""
    return {"sources": []}


@router.post("/{research_id}/rate")
async def rate_research(research_id: str, rating: int):
    """Rate a research session (1-5 stars)."""
    return {"rated": True, "rating": rating}