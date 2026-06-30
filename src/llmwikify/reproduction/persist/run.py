"""Reproduction orchestration — 5-Phase pipeline.

Phase 1: extract  — read wiki TradingStrategy pages → strategy_config
Phase 2: data     — DataRouter fetches OHLCV DataFrame
Phase 3: backtest — run_backtest (Path A: prewritten / Path B: codegen)
Phase 4: analyze  — write BacktestResult + Optimization wiki pages
Phase 5: finalize — update status, record artifacts/events

All errors propagate to "error" status. Sessions persist in the
independent reproduction.db managed by ReproductionDatabase.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from ..backtest_pkg.run_backtest import run_backtest
from ..data_source.router import DataRouter
from ..paper_understanding.extract_strategy import extract_strategy_config
from .sessions import ReproductionDatabase

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    """Bundled inputs for one reproduction run."""
    session_id: str
    wiki: Any
    symbol: str
    start_date: str
    end_date: str
    data_router: DataRouter | None = None
    db: ReproductionDatabase | None = None


def _make_router() -> DataRouter:
    return DataRouter(use_cache=True)


def _build_backtest_page(result, cfg, ctx: RunContext) -> str:
    """Render BacktestResult → markdown page content."""
    lines = [
        "---",
        f"title: Backtest for {cfg['signal_type']}",
        f"strategy_ref: {cfg.get('wiki_page', 'unknown')}",
        f"symbol: {ctx.symbol}",
        f"start: {ctx.start_date}",
        f"end: {ctx.end_date}",
        f"signal_type: {cfg['signal_type']}",
        f"signal_params_json: {cfg.get('signal_params', {})!r}",
        f"sharpe_ratio: {result.sharpe_ratio}",
        f"max_drawdown: {result.max_drawdown}",
        f"win_rate: {result.win_rate}",
        f"total_return: {result.total_return}",
        f"final_cash: {result.final_cash}",
        "---",
        "",
        f"# Backtest — {cfg['signal_type']} on {ctx.symbol}",
        "",
        f"- Session: `{ctx.session_id}`",
        f"- Window: {ctx.start_date} → {ctx.end_date}",
        f"- Status: **{result.status}**",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Sharpe | {result.sharpe_ratio:.4f} |",
        f"| Max drawdown | {result.max_drawdown:.4f} |",
        f"| Win rate | {result.win_rate:.4f} |",
        f"| Total return | {result.total_return:.4f} |",
        f"| Final cash | {result.final_cash:.2f} |",
        f"| Trades | {len(result.trades)} |",
        "",
    ]
    if result.error:
        lines.append(f"## Error\n\n```\n{result.error}\n```\n")
    return "\n".join(lines)


def _build_optimization_page(result, cfg, ctx: RunContext) -> str:
    """Suggest a follow-up parameter sweep based on the current run."""
    lines = [
        "---",
        f"title: Optimization for {cfg['signal_type']}",
        f"strategy_ref: {cfg.get('wiki_page', 'unknown')}",
        f"parameter_grid: {cfg.get('signal_params', {})}",
        "best_params: (TBD)",
        "---",
        "",
        f"# Optimization — {cfg['signal_type']}",
        "",
        "## Current run",
        "",
        f"- Sharpe: {result.sharpe_ratio:.4f}",
        f"- Max DD: {result.max_drawdown:.4f}",
        f"- Win rate: {result.win_rate:.4f}",
        "",
        "## Suggested next sweep",
        "",
        "Manually iterate over signal_params to find a more robust region. "
        "QuantNodes PipelineOptimizer can automate this in a future version.",
        "",
    ]
    return "\n".join(lines)


def run_reproduction(
    ctx: RunContext,
    hook: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the full reproduction pipeline for one session.

    Returns:
        dict with keys: session_id, status, signal_type, signal_params,
                        metrics, source, error (if any)
    """
    db = ctx.db or ReproductionDatabase()
    router = ctx.data_router or _make_router()

    def _emit(event_type: str, **payload: Any) -> None:
        db.record_event(ctx.session_id, event_type, **payload)
        if hook:
            hook(event_type, payload)

    try:
        db.update_status(ctx.session_id, "extracting")
        cfg = extract_strategy_config(ctx.wiki)
        _emit("extract.done",
              signal_type=cfg["signal_type"],
              params=cfg["signal_params"])
        db.update_status(
            ctx.session_id,
            "backtesting",
            signal_type=cfg["signal_type"],
            signal_params=cfg["signal_params"],
        )

        df, source = router.get(ctx.symbol, ctx.start_date, ctx.end_date)
        _emit("data.fetched", source=source, rows=len(df))

        result = run_backtest(
            strategy=cfg["signal_type"],
            data=df,
            config={"signal_params": cfg["signal_params"]},
        )
        _emit("backtest.done",
              status=result.status,
              sharpe=result.sharpe_ratio,
              trades=len(result.trades))

        db.update_status(ctx.session_id, "analyzing")
        try:
            backtest_md = _build_backtest_page(result, cfg, ctx)
            optimization_md = _build_optimization_page(result, cfg, ctx)
            slug = f"{ctx.symbol}-{cfg['signal_type']}".lower().replace(".", "-")
            ctx.wiki.write_page(slug, backtest_md, page_type="BacktestResult")
            db.create_artifact(ctx.session_id, "BacktestResult", f"backtest/{slug}")
            opt_slug = f"{slug}-opt"
            ctx.wiki.write_page(opt_slug, optimization_md, page_type="Optimization")
            db.create_artifact(ctx.session_id, "Optimization", f"optimization/{opt_slug}")
            _emit("wiki.written", slug=slug)
        except Exception as exc:
            logger.warning("wiki write failed (non-fatal): %s", exc)
            _emit("wiki.write.failed", error=str(exc))

        db.update_status(ctx.session_id, "done")

        return {
            "session_id": ctx.session_id,
            "status": "done",
            "signal_type": cfg["signal_type"],
            "signal_params": cfg["signal_params"],
            "source": source,
            "metrics": {
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "total_return": result.total_return,
                "final_cash": result.final_cash,
                "trades": len(result.trades),
            },
        }
    except Exception as exc:
        logger.exception("reproduction failed for session %s", ctx.session_id)
        db.update_status(ctx.session_id, "error", error=str(exc))
        _emit("pipeline.error", error=str(exc))
        return {
            "session_id": ctx.session_id,
            "status": "error",
            "error": str(exc),
        }


__all__ = ["run_reproduction", "RunContext"]
