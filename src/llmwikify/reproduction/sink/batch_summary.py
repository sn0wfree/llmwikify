"""BatchSummarySink — write multi_alpha_<paper_id>.json + .md at batch end.

Replaces v2's `FactorStage._write_summary`:
    BatchSerializer.write_json(self.results, self.config.output_dir / "multi_alpha_001_to_101.json")
    BatchSerializer.write_markdown(self.results, self.config.output_dir / "multi_alpha_summary.md")
    BatchReporter.log_summary(self.results)

PR4 implementation: inline simple JSON/MD aggregation.
PR5 will refactor to delegate to BatchAggregator/BatchSerializer/BatchReporter
(planned in §17.4 PR5).

Output structure:
    output_dir/multi_alpha_<paper_id>.json    # aggregated metrics + per-alpha summary
    output_dir/multi_alpha_<paper_id>.md      # human-readable markdown table
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..backtest.base import FactorResult

logger = logging.getLogger(__name__)


class BatchSummarySink:
    """Writes aggregated batch summary at end of pipeline.

    Args:
        output_dir: Directory to write summary files into.
        paper_id: Used in filename (e.g. "101_alphas_minimal" → "multi_alpha_101_alphas_minimal.json").
                  If None, defaults to "batch".
    """

    def __init__(self, output_dir: Path, paper_id: str = "batch") -> None:
        self._dir = Path(output_dir)
        self._paper_id = paper_id

    @property
    def output_dir(self) -> Path:
        return self._dir

    @property
    def paper_id(self) -> str:
        return self._paper_id

    def write_one(self, result: FactorResult) -> Path:
        """No-op: batch summary is only written at end.

        Returns Path("/dev/null") as sentinel.
        """
        return Path("/dev/null")

    def write_batch(self, results: list[FactorResult]) -> list[Path]:
        """Write aggregated JSON + Markdown summaries.

        Returns:
            List of paths written (typically 2: JSON + Markdown).
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        json_path = self._dir / f"multi_alpha_{self._paper_id}.json"
        md_path = self._dir / f"multi_alpha_{self._paper_id}.md"
        try:
            json_path.write_text(
                json.dumps(self._aggregate_json(results), indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            paths.append(json_path)
        except Exception as exc:
            logger.warning("[sink] batch JSON failed: %s: %s", type(exc).__name__, exc)
        try:
            md_path.write_text(self._aggregate_markdown(results), encoding="utf-8")
            paths.append(md_path)
        except Exception as exc:
            logger.warning("[sink] batch MD failed: %s: %s", type(exc).__name__, exc)
        return paths

    def flush(self) -> None:
        """No-op."""
        return None

    # ─── Internal aggregation (PR5 will extract to BatchAggregator/Serializer) ──

    def _aggregate_json(self, results: list[FactorResult]) -> dict[str, Any]:
        """Aggregate metrics for JSON summary."""
        agg = self._aggregate_metrics(results)
        return {
            "paper_id": self._paper_id,
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
                    "id": r.signal.id,
                    "name": r.signal.name,
                    "status": r.status,
                    "ic_mean": r.backtest.get("ic_mean"),
                    "icir": r.backtest.get("icir"),
                    "ic_winrate": r.backtest.get("win_rate"),
                    "code_chars": r.code_chars,
                    "elapsed_sec": r.elapsed_sec,
                    "stage": r.stage or "",
                    "error": (r.error or "")[:200],
                }
                for r in results
            ],
        }

    def _aggregate_markdown(self, results: list[FactorResult]) -> str:
        """Aggregate metrics for Markdown summary."""
        agg = self._aggregate_metrics(results)
        lines: list[str] = [
            f"# {self._paper_id} — Batch Results",
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
            "| ID | Name | Status | IC | ICIR | Winrate | Code | Elapsed |",
            "|----|------|--------|----|------|---------|------|---------|",
        ]
        for r in results:
            ic = r.backtest.get("ic_mean")
            icir = r.backtest.get("icir")
            wr = r.backtest.get("win_rate")
            ic_s = f"{ic:+.4f}" if isinstance(ic, (int, float)) else "NaN"
            icir_s = f"{icir:+.4f}" if isinstance(icir, (int, float)) else "NaN"
            wr_s = f"{wr * 100:.1f}%" if isinstance(wr, (int, float)) else "NaN"
            lines.append(
                f"| {r.signal.id} | {r.signal.name} | {r.status} | "
                f"{ic_s} | {icir_s} | {wr_s} | {r.code_chars} | {r.elapsed_sec:.1f}s |"
            )
        failed = [r for r in results if r.status != "success"]
        if failed:
            lines += ["", "## Failed", ""]
            for r in failed:
                lines.append(
                    f"- {r.signal.id} (`{r.stage or '?'}`) - {(r.error or '?')[:100]}"
                )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _aggregate_metrics(results: list[FactorResult]) -> dict[str, Any]:
        """NaN-safe average over successful results."""
        import math
        success = [r for r in results if r.status == "success"]
        failed = [r for r in results if r.status != "success"]

        def _finite(xs: list[Any]) -> list[float]:
            return [float(x) for x in xs
                    if isinstance(x, (int, float)) and not math.isnan(x)]

        ic_means = _finite([r.backtest.get("ic_mean") for r in success])
        icirs = _finite([r.backtest.get("icir") for r in success])
        winrates = _finite([r.backtest.get("win_rate") for r in success])

        return {
            "total": len(results),
            "success_count": len(success),
            "failed_count": len(failed),
            "ic_mean": round(sum(ic_means) / len(ic_means), 4) if ic_means else None,
            "icir": round(sum(icirs) / len(icirs), 4) if icirs else None,
            "winrate": round(sum(winrates) / len(winrates), 4) if winrates else None,
        }
