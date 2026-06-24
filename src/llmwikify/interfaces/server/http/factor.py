"""Factor REST endpoints.

Thin FastAPI router for single-factor testing. Matches the pattern of
reproduction.py: global deps set during app startup via set_factor_deps().

Endpoints:
    GET  /api/factor/list            — list factors (legacy alias of /library/list)
    GET  /api/factor/library/list    — list all factors from quant/factors/ (canonical)
    GET  /api/factor/library/{name}  — get full 6-layer YAML definition
    GET  /api/factor/{slug}          — get Factor definition (YAML)
    PUT  /api/factor/library/{name}  — update Factor YAML
    POST /api/factor/{slug}/backtest — run factor backtest (cross-section mode)
    POST /api/factor/{slug}/validate — run L5 validation pipeline
    GET  /api/factor/{slug}/backtest — get past backtest results
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from llmwikify.reproduction.common.config import config

from llmwikify.reproduction.common.run_id import generate_run_id, sanitize_run_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factor", tags=["factor"])

_WIKI_REGISTRY: Any = None
_LLM_CLIENT: Any = None


def set_factor_deps(wiki_registry: Any, llm_client: Any = None) -> None:
    """Set dependencies during app startup."""
    global _WIKI_REGISTRY, _LLM_CLIENT
    _WIKI_REGISTRY = wiki_registry
    _LLM_CLIENT = llm_client


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


# ─── Factor Library endpoints (6-layer YAML) ────────────────
# These MUST be defined before /{slug} to avoid route conflicts.

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
    from llmwikify.reproduction.data_source.router import DataRouter
    from llmwikify.reproduction.sessions import ReproductionDatabase
    from llmwikify.reproduction.data_source.universe import (
        HEDGE_INDEX_CODE,
        get_index_constituents,
        resolve_universe,
    )

    wiki = _get_wiki()
    factor_data = read_factor_yaml(slug)
    if factor_data is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")
    factor = factor_data.get("factor", factor_data)

    # PR-4 (2026-06-21): Loop v4 AST path takes priority over legacy factor_class.
    l5_ast = factor.get("l5", {}).get("ast") or factor.get("l5_ast")
    if l5_ast:
        factor_class = "ast_compiled"
        factor_params = {"ast_json": l5_ast}
    else:
        factor_class = factor.get("subcategory", factor.get("factor_class", "momentum"))
        factor_params = factor.get("l1", {}).get("default_params", factor.get("factor_params", {}))
        if isinstance(factor_params, str):
            try:
                factor_params = json.loads(factor_params)
            except (json.JSONDecodeError, TypeError):
                factor_params = {}

    data_router = DataRouter(use_cache=True, parquet_path=config.get("parquet.path"))
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

        # 5b. Store factor values in DuckDB (background, best-effort)
        try:
            from llmwikify.reproduction.factor_value_store import compute_and_store_factor
            stored_rows = await asyncio.to_thread(
                compute_and_store_factor,
                close_wide=close_wide,
                factor_name=slug,
                factor_class=factor_class,
                factor_params=factor_params,
            )
            if stored_rows > 0:
                logger.info("Stored %d factor values for %s in DuckDB", stored_rows, slug)
        except Exception as exc:
            logger.warning("Factor value storage failed (non-fatal): %s", exc, exc_info=True)

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


@router.get("/{slug}/backtest")
async def get_factor_backtest_results(slug: str, limit: int = 10) -> dict[str, Any]:
    """Get past backtest results for a factor.

    Returns a list of recent backtest runs with IC series and group metrics,
    suitable for rendering L5 charts in the UI.
    """
    from llmwikify.reproduction.sessions import ReproductionDatabase

    db = ReproductionDatabase()
    results = db.list_results(factor_ref=slug, limit=limit)

    runs = []
    for r in results:
        ic_series = json.loads(r.ic_series) if r.ic_series else []
        group_metrics = json.loads(r.group_metrics) if r.group_metrics else {}
        runs.append({
            "run_id": r.run_id,
            "created_at": r.created_at,
            "status": r.status,
            "universe": r.universe,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "metrics": {
                "ic_mean": r.ic_mean,
                "rank_ic_mean": r.rank_ic_mean,
                "icir": r.icir,
                "rank_icir": r.rank_icir,
                "win_rate": r.win_rate,
                "annual_return": r.annual_return,
                "longshort_ann_return": r.longshort_ann_return,
                "longshort_sharpe": r.longshort_sharpe,
                "longshort_max_dd": r.longshort_max_dd,
            },
            "ic_series": ic_series,
            "group_metrics": group_metrics,
        })

    return {"slug": slug, "runs": runs, "total": len(runs)}


class L5ValidateRequest(BaseModel):
    universe: str = Field(default_factory=lambda: config.get("universe.default", "synth"))
    start_date: str = Field(default="2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(default="2024-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    adj_mode: str = Field(default="D")
    n_groups: int = Field(default=5, ge=2, le=10)
    factor_direction: int = Field(default=1)
    cost_bps: float = Field(default=15.0, ge=0, le=100)


@router.post("/{slug}/validate")
async def validate_factor(slug: str, req: L5ValidateRequest) -> dict[str, Any]:
    """Run L5 automated validation pipeline for a factor.

    Executes: backtest → 7 analysis modules → scoring → (LLM hypothesis testing) → write YAML.
    """
    import asyncio
    from llmwikify.reproduction.l5_orchestrator import run_l5_pipeline

    factor = read_factor_yaml(slug)
    if factor is None:
        raise HTTPException(status_code=404, detail=f"Factor '{slug}' not found")

    bt_params = {
        "universe": req.universe,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "adj_mode": req.adj_mode,
        "n_groups": req.n_groups,
        "factor_direction": req.factor_direction,
    }

    # Run in thread pool to avoid blocking
    result = await asyncio.to_thread(
        run_l5_pipeline,
        factor_name=slug,
        llm_client=_LLM_CLIENT,
        cost_bps=req.cost_bps,
        backtest_params=bt_params,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Validation failed"))

    return {
        "slug": slug,
        "status": result["status"],
        "score": result["score"],
        "breakdown": result["breakdown"],
        "message": f"Validation complete: {result['status']} ({result['score']}/100)",
    }
