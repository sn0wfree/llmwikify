"""Backtest engine abstraction — runs generated code against market data.

Public API:
  - FactorResult: per-signal result (code + metrics + status)
  - BacktestEngine: Protocol that runs code and returns metrics dict

Concrete implementations:
  - QuantNodesBacktest: QuantNodes PipelineRunner adapter (replaces v2's
    `_run_pipeline_backtest`)

In PR6, `PaperPipeline._process_one_signal` will:
  1. Call LLM codegen (PR2 territory) → code + factor_series
  2. Write H5 + call `backtest_engine.run(code, h5_path, signal)` → metrics
  3. Wrap everything in `FactorResult` and dispatch to sinks (PR4)

Usage:
    from llmwikify.reproduction.backtest import (
        FactorResult, BacktestEngine, QuantNodesBacktest,
    )
    engine = QuantNodesBacktest(config=run_config)
    metrics = engine.run(code="def compute_factor(df): ...", h5_path=..., signal=signal)
"""
from __future__ import annotations

from .base import BacktestEngine, FactorResult
from .quantnodes import QuantNodesBacktest

__all__ = [
    "FactorResult",
    "BacktestEngine",
    "QuantNodesBacktest",
]
