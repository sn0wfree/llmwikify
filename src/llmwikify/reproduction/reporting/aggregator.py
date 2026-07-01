"""BatchAggregator — pure computation: NaN-safe metrics over batch results.

Two responsibilities (split for clarity, share `import math`):
  - `aggregate(results)`: dict with total/success/failed + averaged IC/ICIR/Winrate
  - `format_metric(value, fmt, na)`: single-value formatter with NaN-safe fallback

All methods are @staticmethod (no state). Operates on `dict` results.

Bug 7 (P1 fix): aggregate + format_metric share one `import math` (no duplicate).
"""
from __future__ import annotations

import math
from typing import Any


class BatchAggregator:
    """Pure computation: NaN-safe metrics over batch results."""

    __slots__ = ()

    @staticmethod
    def aggregate(results: list[dict]) -> dict[str, Any]:
        """Compute aggregate metrics over successful results (NaN-filtered).

        Args:
            results: list of result dicts (each with status / ic_mean / icir / ic_winrate).

        Returns:
            dict with keys:
              - total / success_count / failed_count
              - ic_mean / icir / winrate (rounded to 4 decimals; None if no finite values)
        """
        success = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]

        def _finite(xs: list[Any]) -> list[float]:
            return [float(x) for x in xs
                    if isinstance(x, (int, float)) and not math.isnan(x)]

        ic_means = _finite([r.get("ic_mean") for r in success])
        icirs = _finite([r.get("icir") for r in success])
        winrates = _finite([r.get("ic_winrate") for r in success])

        return {
            "total": len(results),
            "success_count": len(success),
            "failed_count": len(failed),
            "ic_mean": round(sum(ic_means) / len(ic_means), 4) if ic_means else None,
            "icir": round(sum(icirs) / len(icirs), 4) if icirs else None,
            "winrate": round(sum(winrates) / len(winrates), 4) if winrates else None,
        }

    @staticmethod
    def format_metric(value: float | None, fmt: str = "+.4f", na: str = "  NaN") -> str:
        """Format a single metric with NaN-safe fallback.

        Args:
            value: Numeric value (None or NaN → `na` placeholder).
            fmt: f-string format spec (default "+.4f" for IC/ICIR).
            na: Placeholder string for missing values (default 2-space + "NaN").
        """
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return na
        return f"{value:{fmt}}"
