"""factor/ — factor-result lifecycle helpers extracted from v2.

PR9a: ResultFactory — build FactorResult from various inputs (success / fail /
cached dict).

This package sits alongside the existing framework pieces:
  - core/       (PaperPipeline, PaperRecipe, Stage)
  - signal_source/  (SignalSource implementations)
  - backtest/   (BacktestEngine + QuantNodesBacktest)
  - sink/       (Sink implementations)
  - reporting/  (BatchReporter, Aggregator, Serializer)
  - factor/     ← THIS PACKAGE — factor-result lifecycle (build / load / record)

Why a separate package?
  - These helpers encapsulate the per-result state machine (build / load /
    record), which v2 used to inline in FactorStage. Splitting them out:
      (a) makes v2's FactorStage 1108 → ~930 lines (-16%)
      (b) makes the lifecycle independently testable
      (c) makes it clear what a "FactorResult lifecycle" is

Scope of helpers in this package:
  - ResultFactory (PR9a)  : build FactorResult from various inputs
  - SkipLoader    (PR9b)  : read cached JSON results on resume
  - RecordStage   (PR9c)  : atomic record (state + log + persist) after one signal
"""
from .result_factory import ResultFactory

__all__ = ["ResultFactory"]
