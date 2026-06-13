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

from llmwikify.reproduction.config import config
from llmwikify.reproduction.run_id import generate_run_id, sanitize_run_id

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
    """List all factors from the factor library."""
    from llmwikify.reproduction.factor_library import list_factors_by_category

    categories = list_factors_by_category()
    return {"categories": categories}


@router.get("/{slug}")
async def get_factor(slug: str) -> dict[str, Any]:
    """Get a factor's definition from the factor library."""
    from llmwikify.reproduction.factor_library import read_factor_yaml

    factor = read_factor_yaml(slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")
    return {"slug": slug, "factor": factor}


class FactorBacktestRequest(BaseModel):
    # Universe mode (default): cross-section backtest over a stock pool
    universe: str = Field(default_factory=lambda: config.get("universe.default", "synth"))
    adj_mode: str = Field(default="D", description="D / M-end / W-end")
    hedge: str = Field(default="equal", description="equal / HS300 / ZZ500 / SZ50")
    n_groups: int = Field(default_factory=lambda: int(config.get("backtest.n_groups", 5)), ge=2, le=10)
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
    run_id: str,
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
        f"run_id: {run_id}",
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
        f"# Factor Backtest — {factor_slug} ({run_id})",
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


def _persist_factor_result(
    db: Any,
    wiki: Any,
    run_id: str,
    slug: str,
    req: FactorBacktestRequest,
    result: Any,
    source: str,
    factor: dict[str, Any],
) -> Optional[str]:
    """Persist factor backtest result to DB and Wiki.

    All-or-nothing semantics: DB write is committed first, then Wiki.
    If DB write fails, raises; Wiki failure is logged but does not roll back
    DB (Wiki is a mirror, not a source of truth).

    Returns:
        wiki_page path on success, None on wiki failure.
    """
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
        rank_ic_mean=getattr(result, "rank_ic_mean", 0.0),
        icir=result.icir,
        rank_icir=getattr(result, "rank_icir", 0.0),
        win_rate=result.win_rate,
        annual_return=result.annual_return,
        longshort_ann_return=result.longshort_ann_return,
        longshort_sharpe=result.longshort_sharpe,
        longshort_max_dd=getattr(result, "longshort_mdd", 0.0),
        n_stocks_per_date=getattr(result, "n_stocks_per_date", []),
        ic_series=getattr(result, "ic_series", []),
        group_metrics=getattr(result, "group_metrics", {}),
    )
    db.commit()

    backtest_slug = f"factor-{slug}-{sanitize_run_id(run_id)}"
    backtest_md = _build_factor_backtest_page(slug, factor, req, result, source, run_id)
    wiki_page = None
    try:
        from llmwikify.reproduction.quant_wiki import get_quant_wiki
        quant = get_quant_wiki()
        write_result = quant.write_page(backtest_slug, backtest_md, page_type="factorbacktest")
        if "Created" in write_result or "Updated" in write_result:
            wiki_page = f"quant/factorbacktest/{backtest_slug}.md"
        else:
            wiki_page = f"quant/factorbacktest/{backtest_slug}.md"
    except Exception as exc:
        logger.warning("FactorBacktest write failed: %s", exc)

    return wiki_page


@router.post("/{slug}/backtest")
async def backtest_factor(slug: str, req: FactorBacktestRequest) -> dict[str, Any]:
    """Run factor backtest.

    - ``universe != "single"``: cross-section mode using ``run_factor_backtest_universe``.
    - ``universe == "single"``: legacy single-stock mode using ``run_factor_backtest``.
    """
    import asyncio
    from llmwikify.reproduction.factor_library import read_factor_yaml
    from llmwikify.reproduction.router import DataRouter
    from llmwikify.reproduction.sessions import ReproductionDatabase
    from llmwikify.reproduction.universe import (
        HEDGE_INDEX_CODE,
        get_index_constituents,
        resolve_universe,
    )

    wiki = _get_wiki()
    factor_data = read_factor_yaml(slug)
    if factor_data is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")
    factor = factor_data.get("factor", factor_data)

    factor_class = factor.get("subcategory", factor.get("factor_class", "momentum"))
    factor_params = factor.get("l1", {}).get("default_params", factor.get("factor_params", {}))
    if isinstance(factor_params, str):
        try:
            factor_params = json.loads(factor_params)
        except (json.JSONDecodeError, TypeError):
            factor_params = {}

    data_router = DataRouter(use_cache=True)
    run_id = generate_run_id(start=req.start_date, end=req.end_date)
    default_source = config.get("backtest.default_source", "user")

    try:
        # ── Legacy single-stock mode ──────────────────────────────
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

            try:
                db = ReproductionDatabase()
                wiki_page = _persist_factor_result(
                    db=db,
                    wiki=wiki,
                    run_id=run_id,
                    slug=slug,
                    req=req,
                    result=result,
                    source=source,
                    factor=factor,
                )
            except Exception as exc:
                logger.warning("DB write failed (single mode): %s", exc)
                wiki_page = None

            return {
                "slug": slug,
                "factor": factor,
                "symbol": req.symbol,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "data_source": source,
                "status": "success",
                "run_id": run_id,
                "wiki_page": wiki_page,
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
                "total_rebalances": 0,
                "valid_rebalances": 0,
                "source": default_source,
            }

        # ── Cross-section (universe) mode ─────────────────────────
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

        # 6. Persist to DB + Wiki (with rollback on error)
        try:
            db = ReproductionDatabase()
            wiki_page = _persist_factor_result(
                db=db,
                wiki=wiki,
                run_id=run_id,
                slug=slug,
                req=req,
                result=result,
                source=source,
                factor=factor,
            )
        except Exception as exc:
            logger.error("Persist failed, rolling back: %s", exc)
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.error("Rollback failed: %s", rb_exc)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to persist factor backtest result: {exc}",
            )

        return {
            "slug": slug,
            "factor": factor,
            "symbol": f"universe:{req.universe}",
            "start_date": req.start_date,
            "end_date": req.end_date,
            "data_source": source,
            "status": "success",
            "run_id": run_id,
            "wiki_page": wiki_page,
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
            "source": default_source,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Factor backtest failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Factor backtest failed: {exc}",
        )


# ─── Factor Library endpoints (6-layer YAML) ────────────────

@router.get("/library/list")
async def list_factor_library() -> dict[str, Any]:
    """List all factors from the factor library (quant/factors/)."""
    from llmwikify.reproduction.factor_library import list_factors_by_category

    categories = list_factors_by_category()
    return {"categories": categories}


@router.get("/library/{name:path}")
async def get_factor_library(name: str) -> dict[str, Any]:
    """Get a factor's full 6-layer YAML definition."""
    from llmwikify.reproduction.factor_library import read_factor_yaml

    factor = read_factor_yaml(name)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{name}' not found in library")
    return {"name": name, "factor": factor}


@router.put("/library/{name:path}")
async def update_factor_library(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Update a factor's YAML definition."""
    from llmwikify.reproduction.factor_library import write_factor_yaml

    result = write_factor_yaml(name, data)
    return {"status": "ok", "message": result}
