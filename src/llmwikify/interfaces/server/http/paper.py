"""Paper REST endpoints.

Thin FastAPI router for paper reproduction. Matches the pattern of
reproduction.py: global deps set during app startup via set_paper_deps().

Endpoints:
    POST /api/paper/start   — start paper extraction pipeline
    GET  /api/paper/{id}    — get paper extraction status + results
    GET  /api/paper/{id}/artifacts — list wiki pages produced
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/paper", tags=["paper"])

_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None


def set_paper_deps(wiki_registry: Any, llm_client: Any = None) -> None:
    """Set dependencies during app startup.

    Args:
        wiki_registry: Multi-wiki registry.
        llm_client: Optional LLM client. When provided, paper extraction
            actually calls the LLM via repro_extract.yaml; when None,
            extraction returns ``{}`` (legacy offline behavior).
    """
    global _WIKI_REGISTRY, _LLM_CLIENT
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    if wiki_id:
        return _WIKI_REGISTRY.get_wiki(wiki_id)
    return _WIKI_REGISTRY.get_default_wiki()


class PaperStartRequest(BaseModel):
    wiki_id: str = "default"
    paper_id: str
    source_type: str = "pdf"
    source_ref: str
    paper_content: str = ""


@router.post("/start")
async def start_paper_extraction(req: PaperStartRequest) -> dict[str, Any]:
    """Start paper structure extraction pipeline."""
    from llmwikify.reproduction.extract_paper import extract_paper_structure, build_paper_pages

    wiki = _get_wiki(req.wiki_id)

    extraction = await asyncio.to_thread(
        extract_paper_structure,
        paper_content=req.paper_content,
        paper_id=req.paper_id,
        source_type=req.source_type,
        source_ref=req.source_ref,
        llm_client=_LLM_CLIENT,
    )

    pages = build_paper_pages(extraction, req.paper_id)

    written = []
    for page in pages:
        try:
            wiki.write_page(page["page_name"], page["content"], page_type=page.get("page_type"))
            written.append(page["page_name"])
        except Exception as exc:
            logger.warning("failed to write page %s: %s", page["page_name"], exc)

    return {
        "paper_id": req.paper_id,
        "extraction": extraction,
        "pages_written": written,
        "status": "done",
    }


@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict[str, Any]:
    """Get paper extraction results from wiki pages."""
    wiki = _get_wiki()

    # Try to read the logic page
    try:
        logic = wiki.read_page(f"paper-{paper_id}-logic")
    except Exception:
        logic = None

    return {
        "paper_id": paper_id,
        "logic_page": logic,
    }


@router.get("/{paper_id}/artifacts")
async def list_paper_artifacts(paper_id: str) -> dict[str, Any]:
    """List wiki pages produced by paper extraction."""
    wiki = _get_wiki()
    artifacts = []

    for suffix in ["logic", "data", "risks"]:
        page_name = f"paper-{paper_id}-{suffix}"
        try:
            page = wiki.read_page(page_name)
            artifacts.append({
                "kind": "Source",
                "wiki_page": page_name,
                "page_type": "Source",
            })
        except Exception:
            pass

    # Check for Factor page
    try:
        page = wiki.read_page(f"factor-{paper_id}")
        artifacts.append({
            "kind": "Factor",
            "wiki_page": f"factor-{paper_id}",
            "page_type": "Factor",
        })
    except Exception:
        pass

    # Check for Strategy page
    try:
        page = wiki.read_page(f"strategy-{paper_id}")
        artifacts.append({
            "kind": "Strategy",
            "wiki_page": f"strategy-{paper_id}",
            "page_type": "Strategy",
        })
    except Exception:
        pass

    return {
        "paper_id": paper_id,
        "artifacts": artifacts,
    }
