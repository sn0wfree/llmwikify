"""Factor REST endpoints.

Thin FastAPI router for single-factor testing. Matches the pattern of
reproduction.py: global deps set during app startup via set_factor_deps().

Endpoints:
    GET  /api/factor/list            — list all Factor wiki pages
    GET  /api/factor/{slug}          — get Factor definition
    POST /api/factor/{slug}/backtest — run factor backtest (stub for now)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factor", tags=["factor"])

_WIKI_REGISTRY: Any = None


def set_factor_deps(wiki_registry: Any) -> None:
    """Set dependencies during app startup."""
    global _WIKI_REGISTRY
    _WIKI_REGISTRY = wiki_registry


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    if wiki_id:
        return _WIKI_REGISTRY.get_wiki(wiki_id)
    return _WIKI_REGISTRY.get_default_wiki()


@router.get("/list")
async def list_factors() -> dict[str, Any]:
    """List all Factor pages in the wiki."""
    from llmwikify.reproduction.extract_factors import list_factors as _list_factors

    wiki = _get_wiki()
    factors = _list_factors(wiki)
    return {"factors": factors}


@router.get("/{slug}")
async def get_factor(slug: str) -> dict[str, Any]:
    """Get a Factor page's definition."""
    from llmwikify.reproduction.extract_factors import read_factor_from_wiki

    wiki = _get_wiki()
    factor = read_factor_from_wiki(wiki, slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")
    return {"slug": slug, "factor": factor}


class FactorBacktestRequest(BaseModel):
    symbol: str = "600660.SH"
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-31"
    benchmark_code: str = "000300.SH"


@router.post("/{slug}/backtest")
async def backtest_factor(slug: str, req: FactorBacktestRequest) -> dict[str, Any]:
    """Run factor backtest. Stub — returns placeholder until Phase 2.4."""
    from llmwikify.reproduction.extract_factors import read_factor_from_wiki

    wiki = _get_wiki()
    factor = read_factor_from_wiki(wiki, slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")

    # Stub: return factor definition + placeholder metrics
    return {
        "slug": slug,
        "factor": factor,
        "symbol": req.symbol,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "status": "stub",
        "message": "Factor backtest engine not yet implemented (Phase 2.4)",
        "metrics": {
            "ic_mean": 0.0,
            "ic_std": 0.0,
            "icir": 0.0,
            "t_stat": 0.0,
            "win_rate": 0.0,
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
        },
    }
