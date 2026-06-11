"""Paper REST endpoints.

v0.4.0 — async paper extraction with progress tracking.

Endpoints:
    POST /api/paper/start    — kick off async extraction, return session_id
    GET  /api/paper/list     — list all paper/reproduction sessions
    GET  /api/paper/list-raw — list *.pdf files in <project>/raw/
    POST /api/paper/upload   — multipart upload, save to ~/.llmwikify/papers/
    GET  /api/paper/{sid}/status — session + events + artifacts (polled)
    GET  /api/paper/{paper_id}  — legacy: read paper logic page by paper_id
    GET  /api/paper/{paper_id}/artifacts — legacy: list wiki pages by paper_id
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/paper", tags=["paper"])

_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None
_DB: Any = None
_RAW_DIR: Optional[Path] = None
_UPLOAD_DIR: Optional[Path] = None


def set_paper_deps(
    wiki_registry: Any,
    llm_client: Any = None,
    db: Any = None,
    raw_dir: Path | None = None,
    upload_dir: Path | None = None,
) -> None:
    """Set dependencies during app startup."""
    global _WIKI_REGISTRY, _LLM_CLIENT, _DB, _RAW_DIR, _UPLOAD_DIR
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _DB = db
    _RAW_DIR = raw_dir
    _UPLOAD_DIR = upload_dir

    if _RAW_DIR is not None:
        _RAW_DIR.mkdir(parents=True, exist_ok=True)
    if _UPLOAD_DIR is not None:
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Sweep stuck sessions from previous run
    if _DB is not None:
        try:
            for status in ("pending", "extracting", "wiki_building"):
                stuck = _DB.list_sessions(status=status)
                for s in stuck:
                    if s.paper_id or s.source_type in ("pdf", "url", "raw"):
                        _DB.update_status(
                            s.id, "error", error="process restarted before completion"
                        )
                        logger.warning("marked stuck paper session %s as error", s.id)
        except Exception as exc:
            logger.warning("failed to sweep stuck paper sessions: %s", exc)


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    if wiki_id:
        return _WIKI_REGISTRY.get_wiki(wiki_id)
    return _WIKI_REGISTRY.get_default_wiki()


def _safe_filename(paper_id: str) -> str:
    """Sanitize paper_id for use as a filename."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", paper_id.strip())[:80]
    return slug or "paper"


# ─── Request Models ──────────────────────────────────────────


class PaperStartRequest(BaseModel):
    wiki_id: str = "default"
    paper_id: str
    source_type: str = Field(default="pdf", pattern=r"^(pdf|url|raw)$")
    source_ref: str
    paper_content: str = ""


# ─── POST /api/paper/start ───────────────────────────────────


@router.post("/start")
async def start_paper_extraction(req: PaperStartRequest) -> dict[str, Any]:
    """Start async paper structure extraction. Returns session_id immediately."""
    if _DB is None:
        raise HTTPException(status_code=503, detail="Reproduction DB not initialized")

    sid = _DB.create_session(
        wiki_id=req.wiki_id,
        paper_id=req.paper_id,
        source_type=req.source_type,
        source_ref=req.source_ref,
        symbol="",
        start_date="",
        end_date="",
    )
    _DB.record_event(sid, "extract.started", paper_id=req.paper_id)
    logger.info("paper session %s created for %s", sid, req.paper_id)

    # Schedule background task
    asyncio.create_task(
        _run_paper_extraction(
            session_id=sid,
            paper_id=req.paper_id,
            source_type=req.source_type,
            source_ref=req.source_ref,
            paper_content=req.paper_content,
            wiki_id=req.wiki_id,
        )
    )

    return {
        "session_id": sid,
        "status": "pending",
        "paper_id": req.paper_id,
    }


async def _run_paper_extraction(
    session_id: str,
    paper_id: str,
    source_type: str,
    source_ref: str,
    paper_content: str,
    wiki_id: str,
) -> None:
    """Background task: extract → build pages → write wiki → mark done."""
    try:
        _DB.update_status(session_id, "extracting")
        _DB.record_event(session_id, "extract.llm_called")

        # Lazy import to avoid circulars
        from llmwikify.reproduction.extract_paper import (
            build_paper_pages,
            extract_paper_structure,
        )

        extraction = await asyncio.to_thread(
            extract_paper_structure,
            paper_content=paper_content,
            paper_id=paper_id,
            source_type=source_type,
            source_ref=source_ref,
            llm_client=_LLM_CLIENT,
        )
        _DB.record_event(
            session_id,
            "extract.llm_done",
            has_extraction=bool(extraction),
            keys=list(extraction.keys()) if extraction else [],
            extraction=extraction,
        )

        if not extraction:
            # No LLM or empty result — mark done with note
            _DB.update_status(session_id, "done")
            _DB.record_event(
                session_id,
                "finalize.done",
                pages_written=0,
                note="no extraction (no LLM or empty content)",
            )
            logger.info("paper session %s: empty extraction, done", session_id)
            return

        _DB.update_status(session_id, "wiki_building")
        pages = build_paper_pages(extraction, paper_id)
        wiki = _get_wiki(wiki_id)
        written: list[str] = []
        for page in pages:
            try:
                wiki.write_page(
                    page["page_name"],
                    page["content"],
                    page_type=page.get("page_type"),
                )
                _DB.create_artifact(
                    session_id=session_id,
                    kind=page.get("page_type", "Source"),
                    wiki_page=page["page_name"],
                )
                written.append(page["page_name"])
            except Exception as exc:
                logger.warning(
                    "failed to write page %s: %s", page["page_name"], exc
                )

        _DB.record_event(
            session_id, "wiki.written", pages_written=len(written)
        )
        _DB.update_status(session_id, "done")
        _DB.record_event(session_id, "finalize.done", pages_written=len(written))
        logger.info(
            "paper session %s done: %d pages written", session_id, len(written)
        )

    except Exception as exc:
        logger.error("paper session %s failed: %s", session_id, exc)
        logger.debug(traceback.format_exc())
        try:
            _DB.update_status(session_id, "error", error=str(exc))
            _DB.record_event(session_id, "error", message=str(exc))
        except Exception:
            pass


# ─── GET /api/paper/list ─────────────────────────────────────


@router.get("/list")
async def list_paper_sessions(status: Optional[str] = None) -> dict[str, Any]:
    """List paper sessions (filtered to those with source_type=pdf|url|raw)."""
    if _DB is None:
        raise HTTPException(status_code=503, detail="Reproduction DB not initialized")
    all_sessions = _DB.list_sessions(status=status)
    paper_sessions = [
        s.to_dict()
        for s in all_sessions
        if s.source_type in ("pdf", "url", "raw")
    ]
    return {"sessions": paper_sessions}


# ─── GET /api/paper/list-raw ─────────────────────────────────


@router.get("/list-raw")
async def list_raw_papers() -> dict[str, Any]:
    """List *.pdf files in <project>/raw/ directory."""
    if _RAW_DIR is None or not _RAW_DIR.exists():
        return {"files": [], "raw_dir": None}
    files = []
    for p in sorted(_RAW_DIR.glob("*.pdf")):
        if p.is_file():
            stat = p.stat()
            files.append({
                "filename": p.name,
                "path": str(p),
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return {"files": files, "raw_dir": str(_RAW_DIR)}


# ─── POST /api/paper/upload ──────────────────────────────────


@router.post("/upload")
async def upload_paper(
    paper_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a PDF file, save to upload_dir/{safe(paper_id)}.pdf."""
    if _UPLOAD_DIR is None:
        raise HTTPException(status_code=503, detail="Upload dir not initialized")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files accepted")

    safe_name = _safe_filename(paper_id)
    target = _UPLOAD_DIR / f"{safe_name}.pdf"
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (>200MB)")

    await asyncio.to_thread(target.write_bytes, content)
    logger.info("uploaded %d bytes to %s", len(content), target)

    return {
        "paper_id": paper_id,
        "path": str(target),
        "size_bytes": len(content),
        "filename": target.name,
    }


# ─── GET /api/paper/{sid}/status ─────────────────────────────


@router.get("/{session_id}/status")
async def get_paper_status(session_id: str) -> dict[str, Any]:
    """Get current session + events + artifacts (polled by frontend)."""
    if _DB is None:
        raise HTTPException(status_code=503, detail="Reproduction DB not initialized")
    session = _DB.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    events = _DB.get_events(session_id)
    artifacts = _DB.get_artifacts(session_id)
    return {
        "session": session.to_dict(),
        "events": events,
        "artifacts": [a.__dict__ for a in artifacts],
    }


# ─── Legacy endpoints (kept for backward compat) ─────────────


@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict[str, Any]:
    """Legacy: read paper logic page by paper_id."""
    wiki = _get_wiki()
    try:
        logic = wiki.read_page(f"paper-{paper_id}-logic")
    except Exception:
        logic = None
    return {"paper_id": paper_id, "logic_page": logic}


@router.get("/{paper_id}/artifacts")
async def list_paper_artifacts(paper_id: str) -> dict[str, Any]:
    """Legacy: list wiki pages produced for a paper_id."""
    wiki = _get_wiki()
    artifacts = []

    for suffix in [
        "logic", "data", "risks", "operations", "model",
        "sw", "datasets", "references",
    ]:
        page_name = f"paper-{paper_id}-{suffix}"
        try:
            wiki.read_page(page_name)
            artifacts.append({
                "kind": "Source",
                "wiki_page": page_name,
                "page_type": "Source",
            })
        except Exception:
            pass

    for prefix, kind in (("factor-", "Factor"), ("strategy-", "Strategy")):
        page_name = f"{prefix}{paper_id}"
        try:
            wiki.read_page(page_name)
            artifacts.append({
                "kind": kind,
                "wiki_page": page_name,
                "page_type": kind,
            })
        except Exception:
            pass

    return {"paper_id": paper_id, "artifacts": artifacts}


@router.delete("/{session_id}")
async def delete_paper_session(session_id: str) -> dict[str, Any]:
    """Delete a paper session and its events/artifacts."""
    if _DB is None:
        raise HTTPException(status_code=500, detail="DB not initialized")
    ok = _DB.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
