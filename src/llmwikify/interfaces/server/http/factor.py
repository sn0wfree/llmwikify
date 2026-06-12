"""Factor REST endpoints.

Thin FastAPI router for single-factor testing. Matches the pattern of
reproduction.py: global deps set during app startup via set_factor_deps().

Endpoints:
    GET  /api/factor/list            — list all Factor wiki pages
    GET  /api/factor/{slug}          — get Factor definition
    POST /api/factor/{slug}/backtest — run factor backtest (cross-section mode)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    # Universe mode (default): cross-section backtest over a stock pool
    universe: str = "HS300"
    adj_mode: str = Field(default="D", description="D / M-end / W-end")
    hedge: str = Field(default="equal", description="equal / HS300 / ZZ500 / SZ50")
    n_groups: int = Field(default=5, ge=2, le=10)
    factor_direction: int = Field(default=1, description="1 or -1")

    # Date window
    start_date: str = Field(default="2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(default="2024-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")

    # Legacy single-stock mode (when universe == "single")
    symbol: str = "600660.SH"
    benchmark_code: str = "000300.SH"


def _build_factor_backtest_page(
    factor_slug: str,
    factor: dict[str, Any],
    req: FactorBacktestRequest,
    result: Any,
    source: str,
) -> str:
    """Render FactorBacktestResult → markdown page content."""
    lines = [
        "---",
        f"title: Factor Backtest — {factor_slug}",
        f"type: FactorBacktest",
        f"factor_ref: {factor_slug}",
        f"universe: {req.universe}",
        f"adj_mode: {req.adj_mode}",
        f"hedge: {req.hedge}",
        f"start: {req.start_date}",
        f"end: {req.end_date}",
        f"ic_mean: {result.ic_mean:.4f}",
        f"rank_ic_mean: {result.rank_ic_mean:.4f}",
        f"icir: {result.icir:.4f}",
        f"rank_icir: {result.rank_icir:.4f}",
        f"win_rate: {result.win_rate:.4f}",
        f"annual_return: {result.annual_return:.4f}",
        f"longshort_ann_return: {result.longshort_ann_return:.4f}",
        f"longshort_sharpe: {result.longshort_sharpe:.4f}",
        f"data_source: {source}",
        f"status: success",
        "---",
        "",
        f"# Factor Backtest — {factor_slug}",
        "",
        f"- Universe: `{req.universe}`",
        f"- Adj mode: `{req.adj_mode}`",
        f"- Hedge: `{req.hedge}`",
        f"- Window: {req.start_date} → {req.end_date}",
        f"- Data source: {source}",
        "",
        "## IC Analysis",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| IC Mean | {result.ic_mean:.4f} |",
        f"| IC Std | {result.ic_std:.4f} |",
        f"| ICIR | {result.icir:.4f} |",
        f"| t-stat | {result.t_stat:.4f} |",
        f"| Win Rate | {result.win_rate:.4f} |",
        f"| Rank IC Mean | {result.rank_ic_mean:.4f} |",
        f"| Rank ICIR | {result.rank_icir:.4f} |",
        "",
        "## Quantile Returns",
        "",
        f"| Group | Annual Return |",
        f"|---|---|",
    ]
    for group, ret in result.quantile_returns.items():
        lines.append(f"| {group} | {ret:.4f} |")
    lines.append("")
    lines.append("## Long-Short")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Ann Return | {result.longshort_ann_return:.4f} |")
    lines.append(f"| Sharpe | {result.longshort_sharpe:.4f} |")
    lines.append(f"| Max DD | {result.longshort_mdd:.4f} |")
    lines.append("")
    return "\n".join(lines)


@router.post("/{slug}/backtest")
async def backtest_factor(slug: str, req: FactorBacktestRequest) -> dict[str, Any]:
    """Run factor backtest.

    - ``universe != "single"``: cross-section mode using ``run_factor_backtest_universe``.
    - ``universe == "single"``: legacy single-stock mode using ``run_factor_backtest``.
    """
    import asyncio
    import uuid
    from llmwikify.reproduction.extract_factors import read_factor_from_wiki
    from llmwikify.reproduction.paths import WIKI_DIR_FACTOR, result_path, result_dir
    from llmwikify.reproduction.router import DataRouter
    from llmwikify.reproduction.sessions import ReproductionDatabase
    from llmwikify.reproduction.universe import (
        HEDGE_INDEX_CODE,
        get_index_constituents,
        resolve_universe,
    )

    wiki = _get_wiki()
    factor = read_factor_from_wiki(wiki, slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")

    factor_class = factor.get("factor_class", "momentum")
    factor_params = factor.get("factor_params", {})
    if isinstance(factor_params, str):
        try:
            factor_params = json.loads(factor_params)
        except (json.JSONDecodeError, TypeError):
            factor_params = {}

    data_router = DataRouter(use_cache=True)

    # ── Legacy single-stock mode ──────────────────────────────────
    if req.universe == "single":
        data, source = await asyncio.to_thread(
            data_router.get, req.symbol, req.start_date, req.end_date
        )
        from llmwikify.reproduction.factor_backtest import run_factor_backtest
        result = await asyncio.to_thread(
            run_factor_backtest,
            data=data,
            factor_class=factor_class,
            factor_params=factor_params,
        )
        run_id = f"{req.start_date.replace('-', '')}-{req.end_date.replace('-', '')}"
        backtest_slug = f"factor-{slug}"

        # Write to DB
        try:
            db = ReproductionDatabase()
            db.create_result(
                run_id=run_id,
                result_type="factor_backtest",
                factor_ref=slug,
                universe="single",
                start_date=req.start_date,
                end_date=req.end_date,
                status="success",
                adj_mode=req.adj_mode,
                data_source=source,
                ic_mean=result.ic_mean,
                win_rate=result.win_rate,
                annual_return=result.annual_return,
                longshort_ann_return=0.0,
                longshort_sharpe=0.0,
            )
        except Exception as exc:
            logger.warning("DB write failed: %s", exc)

        # Write wiki page
        backtest_md = _build_factor_backtest_page(slug, factor, req, result, source)
        try:
            wiki.write_page(backtest_slug, backtest_md, page_type="FactorBacktest")
        except Exception as exc:
            logger.warning("FactorBacktest wiki write failed: %s", exc)

        return {
            "slug": slug,
            "factor": factor,
            "symbol": req.symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "data_source": source,
            "status": "success",
            "run_id": run_id,
            "wiki_page": f"wiki/factor-backtest/{backtest_slug}.md",
            "metrics": {
                "ic_mean": result.ic_mean,
                "ic_std": result.ic_std,
                "icir": result.icir,
                "t_stat": result.t_stat,
                "win_rate": result.win_rate,
                "annual_return": result.annual_return,
                "max_drawdown": result.max_drawdown,
                "turnover": result.turnover,
                "rank_ic_mean": 0.0,
                "longshort_ann_return": 0.0,
                "longshort_sharpe": 0.0,
            },
            "ic_series": result.ic_series,
            "quantile_returns": result.quantile_returns,
            "quantile_curves": result.quantile_curves,
            "longshort_curve": [],
            "universe": "single",
            "adj_mode": req.adj_mode,
            "n_stocks_per_date": [],
            "group_metrics": {},
        }

    # ── Cross-section (universe) mode ─────────────────────────────
    from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe

    # 1. Resolve stock universe
    symbols = await asyncio.to_thread(resolve_universe, req.universe)
    if not symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve universe '{req.universe}' (no constituents found)",
        )

    # 2. Batch fetch OHLCV
    merged_df, source = await asyncio.to_thread(
        data_router.get_universe, symbols, req.start_date, req.end_date
    )
    if merged_df is None or merged_df.empty:
        raise HTTPException(
            status_code=400,
            detail=f"No data returned for universe '{req.universe}' ({len(symbols)} stocks)",
        )

    # 3. Pivot to wide format [date × Code]
    close_wide = merged_df.pivot_table(
        index="date", columns="Code", values="close", aggfunc="last"
    )
    close_wide = close_wide.sort_index().dropna(how="all")

    # 4. Fetch hedge index close (optional, for future use)
    index_close = None
    if req.hedge in HEDGE_INDEX_CODE:
        hedge_code = HEDGE_INDEX_CODE[req.hedge]
        index_close = await asyncio.to_thread(
            data_router.get_index_close, hedge_code, req.start_date, req.end_date
        )

    # 5. Run cross-section backtest
    result = await asyncio.to_thread(
        run_factor_backtest_universe,
        close_wide=close_wide,
        factor_class=factor_class,
        factor_params=factor_params,
        index_close=index_close,
        adj_mode=req.adj_mode,
        n_groups=req.n_groups,
        factor_direction=req.factor_direction,
        universe=req.universe,
    )

    # 6. Generate run_id and write to DB
    run_id = f"{req.start_date.replace('-', '')}-{req.end_date.replace('-', '')}"

    # Write to DB
    try:
        db = ReproductionDatabase()
        db.create_result(
            run_id=run_id,
            result_type="factor_backtest",
            factor_ref=slug,
            universe=req.universe,
            start_date=req.start_date,
            end_date=req.end_date,
            status="success",
            adj_mode=req.adj_mode,
            hedge=req.hedge,
            data_source=source,
            ic_mean=result.ic_mean,
            rank_ic_mean=result.rank_ic_mean,
            icir=result.icir,
            rank_icir=result.rank_icir,
            win_rate=result.win_rate,
            annual_return=result.annual_return,
            longshort_ann_return=result.longshort_ann_return,
            longshort_sharpe=result.longshort_sharpe,
            longshort_max_dd=result.longshort_mdd,
            n_stocks_per_date=result.n_stocks_per_date,
            ic_series=result.ic_series,
            group_metrics=result.group_metrics,
        )
    except Exception as exc:
        logger.warning("DB write failed: %s", exc)

    # 7. Write wiki page
    backtest_slug = f"factor-{slug}"
    backtest_md = _build_factor_backtest_page(slug, factor, req, result, source)
    try:
        wiki.write_page(backtest_slug, backtest_md, page_type="FactorBacktest")
    except Exception as exc:
        logger.warning("FactorBacktest wiki write failed: %s", exc)

    return {
        "slug": slug,
        "factor": factor,
        "symbol": f"universe:{req.universe}",
        "start_date": req.start_date,
        "end_date": req.end_date,
        "data_source": source,
        "status": "success",
        "run_id": run_id,
        "wiki_page": f"wiki/factor-backtest/{backtest_slug}.md",
        "metrics": {
            "ic_mean": result.ic_mean,
            "ic_std": result.ic_std,
            "icir": result.icir,
            "t_stat": result.t_stat,
            "win_rate": result.win_rate,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "turnover": result.turnover,
            "rank_ic_mean": result.rank_ic_mean,
            "rank_ic_std": result.rank_ic_std,
            "rank_icir": result.rank_icir,
            "longshort_ann_return": result.longshort_ann_return,
            "longshort_sharpe": result.longshort_sharpe,
            "longshort_mdd": result.longshort_mdd,
        },
        "ic_series": result.ic_series,
        "quantile_returns": result.quantile_returns,
        "quantile_curves": result.quantile_curves,
        "longshort_curve": result.longshort_curve,
        "universe": req.universe,
        "adj_mode": result.adj_mode,
        "n_stocks_per_date": result.n_stocks_per_date,
        "group_metrics": result.group_metrics,
        "total_rebalances": result.total_rebalances,
        "valid_rebalances": result.valid_rebalances,
    }
