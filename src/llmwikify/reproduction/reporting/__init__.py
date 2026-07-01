"""Reporting — batch aggregation + serialization + logging.

Public API:
  - BatchAggregator: NaN-safe metric aggregation + format helpers
  - BatchReporter:   Logger output (banner / row / summary)
  - BatchSerializer: JSON / Markdown writers for batch summary
  - factor_results_to_dicts: convert list[FactorResult] → list[dict] for adapters

All classes operate on `dict`-shaped results (not FactorResult directly), so
they work with both:
  - v2's `result` dicts (legacy, PR6 will keep using)
  - FactorResult.to_dict() output (new framework, PR4+ BatchSummarySink)

History:
  Extracted from `scripts/run_101_alphas_v2.py` (P1 refactor `da3f97f`-era).
  The 7 @staticmethod methods on v2's FactorReporter were split into 3
  SRP classes per §16.4 PR1 plan.

Usage:
    from llmwikify.reproduction.reporting import (
        BatchAggregator, BatchReporter, BatchSerializer,
        factor_results_to_dicts,
    )
    dicts = factor_results_to_dicts(results)
    agg = BatchAggregator.aggregate(dicts)
    BatchSerializer.write_json(dicts, Path("summary.json"))
    BatchReporter.log_summary(dicts)
"""
from __future__ import annotations

from .adapters import factor_results_to_dicts
from .aggregator import BatchAggregator
from .reporter import BatchReporter
from .serializer import BatchSerializer

__all__ = [
    "BatchAggregator",
    "BatchReporter",
    "BatchSerializer",
    "factor_results_to_dicts",
]
