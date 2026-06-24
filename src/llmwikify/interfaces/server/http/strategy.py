"""Strategy REST endpoints.

Thin FastAPI router for strategy tracking. Matches the pattern of
reproduction.py: global deps set during app startup via set_strategy_deps().

Endpoints:
    GET  /api/strategy/list              — list all Strategy wiki pages
    GET  /api/strategy/{slug}            — get Strategy definition
    POST /api/strategy/{slug}/backtest   — run strategy backtest
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llmwikify.reproduction.common.utils import parse_frontmatter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

_WIKI_REGISTRY: Any = None


def set_strategy_deps(wiki_registry: Any) -> None:
    """Set dependencies during app startup."""
    global _WIKI_REGISTRY
    _WIKI_REGISTRY = wiki_registry


def _get_wiki(wiki_id: str | None = None) -> Any:
    if _WIKI_REGISTRY is None:
        raise RuntimeError("Wiki registry not initialized")
    if wiki_id:
        return _WIKI_REGISTRY.get_wiki(wiki_id)
    return _WIKI_REGISTRY.get_default_wiki()


def _read_strategy_from_wiki(wiki: Any, slug: str) -> dict[str, Any] | None:
    """Read a Strategy page from quant/strategies/ directory."""
    from llmwikify.reproduction.quant_wiki import get_quant_wiki
    quant = get_quant_wiki()
    return quant.read_page(slug, page_type="strategies")


@router.get("/list")
async def list_strategies() -> dict[str, Any]:
    """List all Strategy pages from quant/."""
    from llmwikify.reproduction.quant_wiki import get_quant_wiki
    quant = get_quant_wiki()
    results = quant.list_pages("strategies")
    return {"strategies": results}


@router.get("/{slug}")
async def get_strategy(slug: str) -> dict[str, Any]:
    """Get a Strategy page's definition."""
    wiki = _get_wiki()
    strategy = _read_strategy_from_wiki(wiki, slug)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{slug}' not found")
    return {"slug": slug, "strategy": strategy}


class StrategyBacktestRequest(BaseModel):
    symbol: str = "600660.SH"
    start_date: str = Field(default="2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(default="2024-03-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_cash: float = 1_000_000.0
    commission: float = 0.001
    benchmark_code: str = "000300.SH"


@router.post("/{slug}/backtest")
async def backtest_strategy(slug: str, req: StrategyBacktestRequest) -> dict[str, Any]:
    """Run strategy backtest using existing run_backtest pipeline."""
    from llmwikify.reproduction.backtest_pkg.run_backtest import run_backtest
    from llmwikify.reproduction.backtest_pkg.metrics import compute_extended_metrics
    from llmwikify.reproduction.data_source.router import DataRouter

    wiki = _get_wiki()
    strategy = _read_strategy_from_wiki(wiki, slug)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{slug}' not found")

    signal_type = strategy.get("signal_type", "unknown")
    signal_params = strategy.get("signal_params", {})

    # Fetch data
    router = DataRouter(use_cache=True)
    data, source = await asyncio.to_thread(
        router.get, req.symbol, req.start_date, req.end_date
    )

    # Fetch benchmark
    benchmark_df = await asyncio.to_thread(
        router.get_benchmark, req.start_date, req.end_date, req.benchmark_code
    )
    benchmark_returns = None
    if benchmark_df is not None and "close" in benchmark_df.columns:
        closes = benchmark_df["close"].values
        benchmark_returns = [
            (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] != 0 else 0.0
            for i in range(1, len(closes))
        ]

    # Run backtest
    result = await asyncio.to_thread(
        run_backtest,
        strategy=signal_type,
        data=data,
        config={
            "signal_params": signal_params,
            "initial_cash": req.initial_cash,
            "commission": req.commission,
        },
    )

    # Compute extended metrics
    extended = compute_extended_metrics(
        trades=result.trades,
        initial_cash=req.initial_cash,
        final_cash=result.final_cash,
        benchmark_returns=benchmark_returns,
    )

    # Use equity_curve and monthly_returns from BacktestResult
    equity_curve = result.equity_curve
    monthly = result.monthly_returns

    return {
        "slug": slug,
        "strategy": strategy,
        "symbol": req.symbol,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "data_source": source,
        "status": result.status,
        "error": result.error,
        "metrics": extended,
        "equity_curve": equity_curve,
        "monthly_returns": monthly,
        "trades_count": len(result.trades),
    }
