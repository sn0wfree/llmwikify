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
    """Run factor backtest using factor_backtest engine."""
    import asyncio
    from llmwikify.reproduction.extract_factors import read_factor_from_wiki
    from llmwikify.reproduction.factor_backtest import run_factor_backtest
    from llmwikify.reproduction.router import DataRouter

    wiki = _get_wiki()
    factor = read_factor_from_wiki(wiki, slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")

    factor_class = factor.get("factor_class", "momentum")
    factor_params = factor.get("factor_params", {})
    if isinstance(factor_params, str):
        import json
        try:
            factor_params = json.loads(factor_params)
        except (json.JSONDecodeError, TypeError):
            factor_params = {}

    # Fetch data
    router = DataRouter(use_cache=True)
    data, source = await asyncio.to_thread(
        router.get, req.symbol, req.start_date, req.end_date
    )

    # Run factor backtest
    result = await asyncio.to_thread(
        run_factor_backtest,
        data=data,
        factor_class=factor_class,
        factor_params=factor_params,
    )

    return {
        "slug": slug,
        "factor": factor,
        "symbol": req.symbol,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "data_source": source,
        "status": "success",
        "metrics": {
            "ic_mean": result.ic_mean,
            "ic_std": result.ic_std,
            "icir": result.icir,
            "t_stat": result.t_stat,
            "win_rate": result.win_rate,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "turnover": result.turnover,
        },
        "ic_series": result.ic_series,
        "quantile_returns": result.quantile_returns,
        "quantile_curves": result.quantile_curves,
    }
