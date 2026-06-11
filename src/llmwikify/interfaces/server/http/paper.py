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
    """Background task: extract → build pages → write wiki → auto-backtest → done."""
    try:
        _DB.update_status(session_id, "extracting")
        _DB.record_event(session_id, "extract.llm_called")

        # Lazy import to avoid circulars
        from llmwikify.reproduction.extract_paper import (
            build_paper_pages,
            extract_paper_structure,
        )

        # Resolve raw filenames to full paths using _RAW_DIR
        # Skip if source_ref is already an absolute path
        if source_type == "raw" and _RAW_DIR is not None and not Path(source_ref).is_absolute():
            source_ref = str(_RAW_DIR / source_ref)

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

        _DB.update_status(session_id, "analyzing")
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

        # Auto-backtest: run factor + strategy backtests if signal was extracted
        suggested = extraction.get("suggested_signal", {})
        signal_type = suggested.get("signal_type", "unknown")
        backtest_results: list[dict[str, Any]] = []

        if signal_type != "unknown":
            _DB.record_event(session_id, "backtest.started", symbol=symbol)
            try:
                from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe
                from llmwikify.reproduction.backtest import run_backtest
                from llmwikify.reproduction.router import DataRouter
                from llmwikify.reproduction.universe import resolve_universe

                router = DataRouter(use_cache=True)

                # Prefer universe from data_requirements if available
                universe_spec = (
                    extraction.get("data_requirements", {}).get("universe", "HS300")
                    or "HS300"
                )
                # Resolve to actual stock list
                symbols = await asyncio.to_thread(resolve_universe, universe_spec)
                # Fall back to single symbol if universe resolution fails
                if not symbols:
                    symbols = [symbol] if symbol else ["000001.SZ"]

                merged_df, source = await asyncio.to_thread(
                    router.get_universe, symbols, start_date, end_date
                )

                if merged_df is not None and not merged_df.empty:
                    # Pivot to wide format [date × Code]
                    close_wide = merged_df.pivot_table(
                        index="date", columns="Code", values="close", aggfunc="last"
                    )
                    close_wide = close_wide.sort_index().dropna(how="all")

                    # Factor backtest (cross-section)
                    factor_slug = None
                    for p in pages:
                        if p.get("page_type") == "Factor":
                            factor_slug = p["page_name"]
                            break

                    if factor_slug:
                        factor_class = signal_type
                        factor_params = suggested.get("signal_params", {})
                        fb_result = await asyncio.to_thread(
                            run_factor_backtest_universe,
                            close_wide=close_wide,
                            factor_class=factor_class,
                            factor_params=factor_params,
                            adj_mode="M-end",
                            n_groups=5,
                            universe=universe_spec,
                        )
                        backtest_results.append({
                            "type": "factor",
                            "slug": factor_slug,
                            "ic_mean": fb_result.ic_mean,
                            "rank_ic_mean": fb_result.rank_ic_mean,
                            "icir": fb_result.icir,
                            "annual_return": fb_result.annual_return,
                            "longshort_ann_return": fb_result.longshort_ann_return,
                            "max_drawdown": fb_result.max_drawdown,
                        })

                    # Strategy backtest (single stock for now)
                    data, _ = await asyncio.to_thread(
                        router.get, symbol, start_date, end_date
                    )
                    strategy_class = suggested.get("strategy_class", "trend_following")
                    sb_result = await asyncio.to_thread(
                        run_backtest,
                        strategy=signal_type,
                        data=data,
                        config={
                            "signal_params": suggested.get("signal_params", {}),
                            "initial_cash": 1_000_000,
                            "commission": 0.001,
                        },
                    )
                    backtest_results.append({
                        "type": "strategy",
                        "status": sb_result.status,
                        "trades_count": len(sb_result.trades),
                        "final_cash": sb_result.final_cash,
                    })

                    _DB.record_event(
                        session_id, "backtest.done",
                        results=backtest_results, source=source,
                    )
                    logger.info("paper %s: auto-backtest done (%s)", session_id, source)
                else:
                    _DB.record_event(session_id, "backtest.skipped", reason="no data")
                    logger.warning("paper %s: no data for backtest (%s)", session_id, symbol)

            except Exception as bt_exc:
                logger.warning("paper %s: auto-backtest failed: %s", session_id, bt_exc)
                _DB.record_event(session_id, "backtest.error", error=str(bt_exc))

        _DB.update_status(session_id, "done")
        _DB.record_event(
            session_id, "finalize.done",
            pages_written=len(written),
            backtest_results=backtest_results,
        )
        logger.info(
            "paper session %s done: %d pages, %d backtests",
            session_id, len(written), len(backtest_results),
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
