"""Reproduction REST endpoints.

Thin FastAPI router exposing run/get/artifacts. Matches the pattern of
research.py: global deps set during app startup via set_repro_deps().

Endpoints:
    POST /api/reproduction/start   — kick off a run_reproduction
    GET  /api/reproduction/{sid}   — fetch session + final result
    GET  /api/reproduction/{sid}/artifacts — list wiki pages produced
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llmwikify.reproduction.run import RunContext, run_reproduction
from llmwikify.reproduction.sessions import ReproductionDatabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reproduction", tags=["reproduction"])

_REPRO_DB: ReproductionDatabase | None = None
_WIKI_REGISTRY: Any = None


def set_repro_deps(db: ReproductionDatabase, wiki_registry: Any) -> None:
    """Set dependencies during app startup. Mirrors research.set_research_deps."""
    global _REPRO_DB, _WIKI_REGISTRY
    _REPRO_DB = db
    _WIKI_REGISTRY = wiki_registry


def _get_db() -> ReproductionDatabase:
    if _REPRO_DB is None:
        raise RuntimeError("Reproduction deps not initialized")
    return _REPRO_DB


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    if wiki_id:
        return _WIKI_REGISTRY.get_wiki(wiki_id)
    return _WIKI_REGISTRY.get_default_wiki()


class StartRequest(BaseModel):
    wiki_id: str = "default"
    paper_id: str
    source_type: str = "pdf"
    source_ref: str
    symbol: str
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.get("/list")
async def list_sessions(status: str | None = None) -> dict[str, Any]:
    """List all reproduction sessions, optionally filtered by status."""
    db = _get_db()
    sessions = db.list_sessions(status=status)
    return {
        "sessions": [s.to_dict() for s in sessions],
    }


@router.post("/start")
async def start_reproduction(req: StartRequest) -> dict[str, Any]:
    db = _get_db()
    wiki = _get_wiki(req.wiki_id)
    sid = db.create_session(
        wiki_id=req.wiki_id,
        paper_id=req.paper_id,
        source_type=req.source_type,
        source_ref=req.source_ref,
        symbol=req.symbol,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    ctx = RunContext(
        session_id=sid, wiki=wiki, symbol=req.symbol,
        start_date=req.start_date, end_date=req.end_date,
        db=db,
    )
    result = await asyncio.to_thread(run_reproduction, ctx)
    return {"session_id": sid, **result}


@router.get("/{session_id}")
async def get_reproduction(session_id: str) -> dict[str, Any]:
    db = _get_db()
    sess = db.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    events = db.get_events(session_id)
    return {
        "session": sess.to_dict(),
        "events": events[-10:],
    }


@router.get("/{session_id}/artifacts")
async def list_artifacts(session_id: str) -> dict[str, Any]:
    db = _get_db()
    artifacts = db.get_artifacts(session_id)
    return {
        "session_id": session_id,
        "artifacts": [
            {
                "kind": a.kind,
                "wiki_page": a.wiki_page,
                "meta": json.loads(a.meta_json),
                "created_at": a.created_at,
            }
            for a in artifacts
        ],
    }