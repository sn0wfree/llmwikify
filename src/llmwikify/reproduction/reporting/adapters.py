"""Adapters between FactorResult (PR3) and dict-based reporting (v2 legacy).

The reporting classes (BatchAggregator / BatchReporter / BatchSerializer) operate
on `dict` results for v2 compatibility. The new framework produces `FactorResult`
objects (PR3). This module bridges the two.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..backtest.base import FactorResult


def factor_results_to_dicts(results: list[FactorResult]) -> list[dict[str, Any]]:
    """Convert list[FactorResult] → list[dict] for BatchAggregator/Serializer/Reporter.

    Each dict has the same shape as v2's result dicts (status / stage / error /
    code / code_chars / ic_mean / icir / ic_winrate / elapsed_sec / alpha_index).
    """
    return [r.to_dict() for r in results]
