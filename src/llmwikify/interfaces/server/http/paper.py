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
_RAW_DIR: Path | None = None
_UPLOAD_DIR: Path | None = None
_PARQUET_PATH: str | None = None


def set_paper_deps(
    wiki_registry: Any,
    llm_client: Any = None,
    db: Any = None,
    raw_dir: Path | None = None,
    upload_dir: Path | None = None,
    parquet_path: str | None = None,
) -> None:
    """Set dependencies during app startup."""
    global _WIKI_REGISTRY, _LLM_CLIENT, _DB, _RAW_DIR, _UPLOAD_DIR, _PARQUET_PATH
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client
    _DB = db
    _RAW_DIR = raw_dir
    _UPLOAD_DIR = upload_dir
    _PARQUET_PATH = parquet_path

    if _RAW_DIR is not None:
        _RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Sweep stuck sessions from previous run
    if _DB is not None:
        try:
            for status in ("pending", "extracting", "analyzing"):
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
    wiki_id: str | None = None
    paper_id: str
    source_type: str = Field(default="pdf", pattern=r"^(pdf|url|raw)$")
    source_ref: str
    paper_content: str = ""
    # Auto-backtest params (optional)
    symbol: str = "000300.SH"
    start_date: str = Field(default="2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(default="2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")


# ─── POST /api/paper/start ───────────────────────────────────


@router.post("/start")
async def start_paper_extraction(req: PaperStartRequest) -> dict[str, Any]:
    """Start async paper structure extraction. Returns session_id immediately."""
    if _DB is None:
        raise HTTPException(status_code=503, detail="Reproduction DB not initialized")

    # Resolve wiki_id: None → use default wiki's id
    wiki_id = req.wiki_id
    if not wiki_id and _WIKI_REGISTRY is not None:
        try:
            wiki_id = _WIKI_REGISTRY.get_default_wiki_id() or "default"
        except Exception:
            wiki_id = "default"
    elif not wiki_id:
        wiki_id = "default"

    sid = _DB.create_session(
        wiki_id=wiki_id,
        paper_id=req.paper_id,
        source_type=req.source_type,
        source_ref=req.source_ref,
        symbol=req.symbol,
        start_date=req.start_date,
        end_date=req.end_date,
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
            wiki_id=wiki_id,
            symbol=req.symbol,
            start_date=req.start_date,
            end_date=req.end_date,
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
    symbol: str = "000300.SH",
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
) -> None:
    """Background task: 调用 UnifiedWorkflow 执行完整流水线."""
    from llmwikify.reproduction.pipeline.workflow import UnifiedWorkflow, WorkflowConfig

    try:
        _DB.update_status(session_id, "extracting")
        _DB.record_event(session_id, "extract.llm_called")

        # Resolve raw filenames to full paths using _RAW_DIR
        if source_type == "raw" and _RAW_DIR is not None and not Path(source_ref).is_absolute():
            source_ref = str(_RAW_DIR / source_ref)

        config = WorkflowConfig(
            paper_id=paper_id,
            source_type=source_type,
            source_ref=source_ref,
            paper_content=paper_content,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            llm_client=_LLM_CLIENT,
        )

        workflow = UnifiedWorkflow(config)
        result = await asyncio.to_thread(workflow.run)

        # DB 更新: artifacts
        for factor_name in result.written_factors:
            _DB.create_artifact(
                session_id=session_id,
                kind="Factor",
                wiki_page=f"factor-{factor_name}",
            )

        # DB 更新: events
        _DB.record_event(
            session_id,
            "extract.llm_done",
            n_signals=result.n_signals,
            n_coded=result.n_coded,
        )
        if result.backtest_results:
            _DB.record_event(
                session_id,
                "backtest.done",
                results=result.backtest_results,
            )

        if result.success:
            _DB.update_status(session_id, "done")
            _DB.record_event(
                session_id,
                "finalize.done",
                written_factors=result.written_factors,
                backtest_results=result.backtest_results,
            )
            logger.info(
                "paper session %s done: %d signals, %d coded, %d written, %d backtests",
                session_id,
                result.n_signals,
                result.n_coded,
                len(result.written_factors),
                len(result.backtest_results),
            )
        else:
            _DB.update_status(session_id, "error", error=result.error)
            _DB.record_event(session_id, "error", message=result.error)
            logger.error("paper session %s failed: %s", session_id, result.error)

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
async def list_paper_sessions(status: str | None = None) -> dict[str, Any]:
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
    file: UploadFile = File(...),  # noqa: B008
) -> dict[str, Any]:
    """Upload a PDF file, save to raw/{safe(paper_id)}.pdf."""
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
    from llmwikify.reproduction.paper_understanding.quant_wiki import get_quant_wiki
    quant = get_quant_wiki()
    try:
        logic = quant.read_page(f"paper-{paper_id}-logic", page_type="papers")
    except Exception:
        logic = None
    return {"paper_id": paper_id, "logic_page": logic}


@router.get("/{paper_id}/artifacts")
async def list_paper_artifacts(paper_id: str) -> dict[str, Any]:
    """Legacy: list pages produced for a paper_id from quant/."""
    from llmwikify.reproduction.paper_understanding.quant_wiki import get_quant_wiki
    quant = get_quant_wiki()
    artifacts = []

    for suffix in [
        "logic", "data", "risks", "operations", "model",
        "sw", "datasets", "references",
    ]:
        page_name = f"paper-{paper_id}-{suffix}"
        result = quant.read_page(page_name, page_type="papers")
        if result is not None:
            artifacts.append({
                "kind": "Source",
                "wiki_page": page_name,
                "page_type": "Source",
            })

    for prefix, kind in (("factor-", "Factor"), ("strategy-", "Strategy")):
        page_name = f"{prefix}{paper_id}"
        if kind == "Factor":
            # Check if factor YAML exists
            from llmwikify.reproduction.persist.factor_library import read_factor_yaml
            factor = read_factor_yaml(f"factor_{paper_id}_{page_name}")
            if factor is not None:
                artifacts.append({
                    "kind": kind,
                    "wiki_page": page_name,
                    "page_type": kind,
                })
        else:
            result = quant.read_page(page_name, page_type="strategies")
            if result is not None:
                artifacts.append({
                    "kind": kind,
                    "wiki_page": page_name,
                    "page_type": kind,
                })

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
