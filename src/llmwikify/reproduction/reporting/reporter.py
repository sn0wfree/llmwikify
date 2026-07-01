"""BatchReporter — Logger output (banner / row / summary).

Three responsibilities:
  - `log_banner()`: batch runner header (101-Alpha / generic)
  - `log_row(idx, result, elapsed_cum)`: per-alpha row log
  - `log_summary(results)`: end-of-batch summary

All @staticmethod (no state). Operates on `dict` results.

Note: `log_banner()` hardcodes "101-Alpha" for v2 compat. For other papers,
use `log_summary(results)` which adapts to paper-specific data.
"""
from __future__ import annotations

import logging

from .aggregator import BatchAggregator

logger = logging.getLogger(__name__)


class BatchReporter:
    """Logger output: banner / row / summary."""

    __slots__ = ()

    @staticmethod
    def log_banner() -> None:
        """Log batch runner header (v2 compat: '101-Alpha')."""
        logger.info("=" * 100)
        logger.info("  101-Alpha Batch Runner (v2)")
        logger.info("=" * 100)

    @staticmethod
    def log_row(idx: int, result: dict, elapsed_cum: float) -> None:
        """Log one alpha row result.

        Format: `  001  success   +0.0100  +0.1000  51.0%   12.5s`
        """
        status: str = result.get("status", "unknown")
        elapsed: float = result.get("elapsed_sec", 0)
        note: str = result.get("stage", "") if status != "success" else ""

        ic_str = BatchAggregator.format_metric(result.get("ic_mean"))
        icir_str = BatchAggregator.format_metric(result.get("icir"))
        wr = result.get("ic_winrate")
        wr_str = f"{wr * 100:5.1f}%" if isinstance(wr, (int, float)) else "  NaN"

        logger.info(
            "  %3d  %-8s %10s %10s %8s  %6.1fs  %s",
            idx, status, ic_str, icir_str, wr_str, elapsed, note,
        )

    @staticmethod
    def log_summary(results: list[dict]) -> None:
        """Log batch summary (paper-agnostic)."""
        agg = BatchAggregator.aggregate(results)
        success = agg["success_count"]
        failed = agg["failed_count"]

        logger.info("=" * 100)
        logger.info("  Summary")
        logger.info("=" * 100)
        logger.info(
            "  Total:  %d  |  Success: %d  |  Failed: %d",
            agg["total"], success, failed,
        )
        if agg["ic_mean"] is not None:
            wr_pct = (agg["winrate"] or 0) * 100
            logger.info(
                "  Avg IC: %+.4f  |  Avg ICIR: %+.4f  |  Avg Winrate: %.1f%%",
                agg["ic_mean"], agg["icir"], wr_pct,
            )
        if failed:
            logger.info("  Failed alphas:")
            for r in results:
                if r.get("status") == "success":
                    continue
                idx = r.get("alpha_index")
                idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
                logger.info(
                    "    alpha-%s: %s - %s",
                    idx_s, r.get("stage", "?"), (r.get("error", "?") or "")[:80],
                )
        logger.info("=" * 100)
