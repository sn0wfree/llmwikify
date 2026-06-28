"""BatchSerializer — JSON / Markdown writers for batch summary.

Two responsibilities:
  - `write_json(results, path)`: aggregated summary as JSON
  - `write_markdown(results, path)`: human-readable table

All @staticmethod (no state). Operates on `dict` results.

Uses BatchAggregator internally for metrics.

v2 compat note:
  - Markdown header hardcodes "# 101-Alpha Batch Results (v2)"
  - For other papers, use the BatchSummarySink which delegates here but
    uses the paper_id from recipe.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .aggregator import BatchAggregator


class BatchSerializer:
    """JSON / Markdown writers for batch summary."""

    __slots__ = ()

    @staticmethod
    def write_json(results: list[dict], path: Path) -> None:
        """Write batch summary as JSON.

        Schema:
          {
            "total": N,
            "success_count": N,
            "failed_count": N,
            "aggregate": {
              "ic_mean_avg": float | None,
              "icir_avg": float | None,
              "winrate_avg": float | None
            },
            "alphas": [
              {"index", "status", "ic_mean", "icir", "ic_winrate",
               "code_chars", "elapsed_sec", "stage", "error (truncated 200)"}
            ]
          }
        """
        agg = BatchAggregator.aggregate(results)
        summary: dict[str, Any] = {
            "total": agg["total"],
            "success_count": agg["success_count"],
            "failed_count": agg["failed_count"],
            "aggregate": {
                "ic_mean_avg": agg["ic_mean"],
                "icir_avg": agg["icir"],
                "winrate_avg": agg["winrate"],
            },
            "alphas": [
                {
                    "index": r.get("alpha_index"),
                    "status": r.get("status"),
                    "ic_mean": r.get("ic_mean"),
                    "icir": r.get("icir"),
                    "ic_winrate": r.get("ic_winrate"),
                    "code_chars": r.get("code_chars"),
                    "elapsed_sec": r.get("elapsed_sec"),
                    "stage": r.get("stage", ""),
                    "error": (r.get("error", "") or "")[:200],
                }
                for r in results
            ],
        }
        path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def write_markdown(results: list[dict], path: Path) -> None:
        """Write batch summary as Markdown table.

        Header: "# 101-Alpha Batch Results (v2)" — hardcoded for v2 compat.
        For paper-agnostic header, BatchSummarySink uses paper_id from recipe.
        """
        agg = BatchAggregator.aggregate(results)

        lines: list[str] = [
            "# 101-Alpha Batch Results (v2)",
            "",
            f"- Total: {agg['total']} | Success: {agg['success_count']} | Failed: {agg['failed_count']}",
        ]
        if agg["ic_mean"] is not None:
            wr_pct = (agg["winrate"] or 0) * 100
            lines.append(
                f"- Avg IC: {agg['ic_mean']:+.4f} | "
                f"Avg ICIR: {agg['icir']:+.4f} | "
                f"Avg Winrate: {wr_pct:.1f}%"
            )
        lines += [
            "",
            "| Alpha | Status | IC | ICIR | Winrate | Code | Elapsed |",
            "|-------|--------|----|------|---------|------|---------|",
        ]
        for r in results:
            idx = r.get("alpha_index")
            st: str = r.get("status", "?")
            idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            ic_s = BatchAggregator.format_metric(r.get("ic_mean"), na="NaN")
            icir_s = BatchAggregator.format_metric(r.get("icir"), na="NaN")
            wr = r.get("ic_winrate")
            wr_s = (
                f"{wr * 100:.1f}%"
                if isinstance(wr, float) and not (wr != wr)  # not NaN
                else "NaN"
            )
            cc = r.get("code_chars", 0) or 0
            el = r.get("elapsed_sec", 0) or 0
            lines.append(
                f"| alpha-{idx_s} | {st} | {ic_s} | {icir_s} | {wr_s} | {cc} | {el:.1f}s |"
            )

        failed = [r for r in results if r.get("status") != "success"]
        if failed:
            lines += ["", "## Failed Alphas", ""]
            for r in failed:
                idx = r.get("alpha_index")
                idx_s = f"{idx:03d}" if isinstance(idx, int) else str(idx)
                lines.append(
                    f"- alpha-{idx_s}: `{r.get('stage', '?')}` - "
                    f"{(r.get('error', '?') or '')[:100]}"
                )

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
