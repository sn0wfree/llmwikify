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
_PARQUET_PATH: Optional[str] = None


def _extract_factor_from_page(page: dict, paper_id: str, extraction: dict | None = None) -> dict:
    """Convert a factor wiki page to 6-layer YAML structure.

    Uses LLM-extracted factor_metadata (when extraction is provided) for
    full 6-layer population. Falls back to wiki frontmatter + defaults
    when extraction is unavailable.

    Returns dict with keys:
        name: factor path relative to quant/factors/ (e.g., 'stock/price/momentum_20d')
        factor: the 6-layer factor dict
    """
    from llmwikify.reproduction.utils import parse_frontmatter
    from llmwikify.reproduction.utils import generate_slug

    fm = parse_frontmatter(page.get("content", ""))
    metadata = (extraction or {}).get("factor_metadata", {})

    factor_class = fm.get("factor_class", fm.get("signal_type", "unknown"))
    signal_params = fm.get("signal_params", fm.get("factor_params", {}))
    if isinstance(signal_params, str):
        import json
        try:
            signal_params = json.loads(signal_params)
        except (json.JSONDecodeError, TypeError):
            signal_params = {}

    title = fm.get("title", page.get("page_name", f"factor-{paper_id}"))
    slug = generate_slug(title)

    # Path: prefer metadata, fall back to fm/frontmatter
    asset_type = metadata.get("asset_type") or fm.get("asset_type") or "stock"
    category = metadata.get("category") or fm.get("category") or "price"
    subcategory = metadata.get("subcategory") or factor_class

    factor_name = f"{asset_type}/{category}/{slug}"

    # L1: prefer metadata.l1, fall back to frontmatter + defaults
    meta_l1 = metadata.get("l1", {})
    l1 = {
        "definition": meta_l1.get("definition") or fm.get("reasoning") or f"Factor extracted from {paper_id}",
        "formula": meta_l1.get("formula") or "TBD",
        "input_columns": meta_l1.get("input_columns") or ["close"],
        "frequency": meta_l1.get("frequency") or "日频",
        "output_schema": "[date × Code]",
        "nan_meaning": "TBD",
        "default_params": meta_l1.get("default_params") or signal_params or {},
        "param_constraints": meta_l1.get("param_constraints") or "TBD",
        "business_constraints": meta_l1.get("business_constraints") or "TBD",
    }

    # L2: prefer metadata.l2, fall back to generic step
    meta_l2 = metadata.get("l2", {})
    meta_steps = meta_l2.get("calculation_steps") or []
    if not meta_steps:
        sig_gen = (extraction or {}).get("operation_steps", {}).get("signal_generation", "")
        if sig_gen:
            meta_steps = [
                {"step": i + 1, "description": s.strip()}
                for i, s in enumerate(sig_gen.split("\n")) if s.strip()
            ]
        else:
            meta_steps = [{"step": 1, "description": f"计算 {factor_class} 因子"}]
    l2 = {
        "calculation_steps": meta_steps,
        "edge_case_handling": meta_l2.get("edge_case_handling", "TBD"),
        "missing_value_handling": meta_l2.get("missing_value_handling", "TBD"),
        "data_alignment": "T+1",
        "complexity": meta_l2.get("complexity", "O(T × N)"),
    }

    # L3: prefer metadata.l3, fall back to strategy_logic
    meta_l3 = metadata.get("l3", {})
    strategy_logic = (extraction or {}).get("strategy_logic", {})
    l3 = {
        "financial_intuition": meta_l3.get("financial_intuition") or fm.get("reasoning", "TBD"),
        "market_behavior": meta_l3.get("market_behavior") or strategy_logic.get("alpha_source", "TBD"),
        "theoretical_basis": meta_l3.get("theoretical_basis") or strategy_logic.get("core_hypothesis", "TBD"),
        "historical_effectiveness": meta_l3.get("historical_effectiveness") or strategy_logic.get("market_logic", "TBD"),
        "related_factors": meta_l3.get("related_factors", "TBD"),
    }

    # L4: prefer metadata.l4, fall back to improvement_directions as insights
    meta_l4 = metadata.get("l4", {})
    improvement_dirs = (extraction or {}).get("strengths_weaknesses", {}).get("improvement_directions", [])
    hypotheses = meta_l4.get("hypotheses", [])
    # Mark hypotheses as unverified (just registered)
    for h in hypotheses:
        if "status" not in h:
            h["status"] = "未验证"
    l4 = {
        "hypotheses": hypotheses,
        "hypothesis_limit": 5,
        "archived_hypotheses": [],
        "meaning_summary": meta_l4.get("meaning_summary") or fm.get("reasoning", "TBD"),
        "key_insights": meta_l4.get("key_insights", improvement_dirs),
        "uncertainty": meta_l4.get("uncertainty", "TBD"),
        "final_meaning": None,
    }

    factor_dict = {
        "name": factor_name.replace("/", "_"),
        "name_cn": title,
        "asset_type": asset_type,
        "category": category,
        "subcategory": subcategory,
        "version": 1,
        "status": "已注册",
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "l4": l4,
        "l5": {},
        "l6": {},
    }

    return {"name": factor_name, "factor": factor_dict}


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

        # Import quant storage
        from llmwikify.reproduction.quant_wiki import get_quant_wiki
        from llmwikify.reproduction.factor_library import write_factor_yaml
        from llmwikify.reproduction.extract_paper import _extract_factors_from_list
        quant = get_quant_wiki()

        written: list[str] = []

        # ── Multi-factor branch: factor_list[] from extraction ──
        factor_list_factors = _extract_factors_from_list(extraction, paper_id)
        if factor_list_factors:
            logger.info(
                "paper %s: multi-factor mode, %d factors from factor_list",
                session_id, len(factor_list_factors),
            )
            for fl in factor_list_factors:
                try:
                    write_factor_yaml(fl["name"], {"factor": fl["factor"]})
                    _DB.create_artifact(
                        session_id=session_id,
                        kind="Factor",
                        wiki_page=f"factor-{fl['name']}",
                    )
                    written.append(f"factor-{fl['name']}")
                except Exception as exc:
                    logger.warning(
                        "failed to write factor %s: %s", fl["name"], exc
                    )

            # Also write Source pages (strategy_logic, data_requirements, etc.)
            pages = build_paper_pages(extraction, paper_id)
            for page in pages:
                pt = page.get("page_type", "Source")
                if pt == "Source":
                    try:
                        quant.write_page(
                            page["page_name"], page["content"], page_type="papers"
                        )
                        _DB.create_artifact(
                            session_id=session_id, kind=pt, wiki_page=page["page_name"]
                        )
                        written.append(page["page_name"])
                    except Exception as exc:
                        logger.warning("failed to write page %s: %s", page["page_name"], exc)

            # Auto-backtest all factor_list factors
            _DB.record_event(session_id, "backtest.started", symbol=symbol)
            backtest_results: list[dict[str, Any]] = []
            try:
                from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe
                from llmwikify.reproduction.router import DataRouter
                from llmwikify.reproduction.universe import resolve_universe

                router = DataRouter(use_cache=True, parquet_path=str(_PARQUET_PATH) if _PARQUET_PATH else None)
                universe_spec = extraction.get("data_requirements", {}).get("universe", "HS300") or "HS300"
                symbols = await asyncio.to_thread(resolve_universe, universe_spec)

                for fl in factor_list_factors:
                    try:
                        factor_name = fl["name"]
                        factor_data = fl["factor"]
                        code = factor_data.get("l1", {}).get("code", "") or factor_data.get("l2", {}).get("generated_code", "")
                        factor_class = "formula" if code else "momentum"

                        result = await asyncio.to_thread(
                            run_factor_backtest_universe,
                            data_router=router,
                            symbols=symbols,
                            factor_class=factor_class,
                            factor_params={**factor_data.get("l1", {}).get("default_params", {}), "code": code} if code else factor_data.get("l1", {}).get("default_params", {}),
                            start_date=start_date,
                            end_date=end_date,
                            adj_mode="D",
                            n_groups=5,
                            cost_bps=15.0,
                        )
                        bt_result = result["result"]
                        backtest_results.append({
                            "factor_name": factor_name,
                            "factor_class": factor_class,
                            "ic_summary": result.get("ic_summary"),
                            "group_return": result.get("group_return"),
                            "long_short": result.get("long_short"),
                            "score": bt_result.score,
                            "turnover": getattr(bt_result, "turnover", None),
                        })

                        # Store to DuckDB
                        try:
                            from llmwikify.reproduction.factor_value_store import store_factor_values
                            if result.get("factor_wide") is not None:
                                store_factor_values(
                                    factor_name=factor_name,
                                    factor_wide=result["factor_wide"],
                                    source=f"paper/{paper_id}",
                                )
                        except Exception as db_exc:
                            logger.warning("paper %s: DuckDB store failed for %s: %s", session_id, factor_name, db_exc)

                    except Exception as exc:
                        logger.warning("paper %s: backtest failed for %s: %s", session_id, fl["name"], exc)
                        backtest_results.append({"factor_name": fl["name"], "error": str(exc)})

                _DB.record_event(
                    session_id, "backtest.done",
                    results=backtest_results, source=source,
                )
                logger.info("paper %s: multi-factor backtest done (%d factors)", session_id, len(backtest_results))

            except Exception as bt_exc:
                logger.warning("paper %s: multi-factor backtest failed: %s", session_id, bt_exc)
                _DB.record_event(session_id, "backtest.error", error=str(bt_exc))

        else:
            # ── Single-factor branch (legacy) ──
            pages = build_paper_pages(extraction, paper_id)
            for page in pages:
                try:
                    pt = page.get("page_type", "Source")
                    if pt == "Factor":
                        extracted = _extract_factor_from_page(page, paper_id, extraction=extraction)
                        factor_name = extracted["name"]
                        factor_data = extracted["factor"]
                        write_factor_yaml(factor_name, {"factor": factor_data})
                    else:
                        quant_page_type = "papers" if pt == "Source" else "strategies"
                        quant.write_page(
                            page["page_name"], page["content"], page_type=quant_page_type,
                        )
                    _DB.create_artifact(
                        session_id=session_id, kind=pt, wiki_page=page["page_name"],
                    )
                    written.append(page["page_name"])
                except Exception as exc:
                    logger.warning("failed to write page %s: %s", page["page_name"], exc)

            _DB.record_event(session_id, "wiki.written", pages_written=len(written))

            # Auto-backtest (single-factor legacy)
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

                    router = DataRouter(use_cache=True, parquet_path=str(_PARQUET_PATH) if _PARQUET_PATH else None)

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
    from llmwikify.reproduction.quant_wiki import get_quant_wiki
    quant = get_quant_wiki()
    try:
        logic = quant.read_page(f"paper-{paper_id}-logic", page_type="papers")
    except Exception:
        logic = None
    return {"paper_id": paper_id, "logic_page": logic}


@router.get("/{paper_id}/artifacts")
async def list_paper_artifacts(paper_id: str) -> dict[str, Any]:
    """Legacy: list pages produced for a paper_id from quant/."""
    from llmwikify.reproduction.quant_wiki import get_quant_wiki
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
            from llmwikify.reproduction.factor_library import read_factor_yaml
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
