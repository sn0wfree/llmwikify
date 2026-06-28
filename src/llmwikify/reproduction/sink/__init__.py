"""Sink abstraction — pluggable output destinations for FactorResult.

Public API:
  - Sink: Protocol that writes one FactorResult (or batch) somewhere
  - SingleJsonSink: writes output_dir/single_factor_<id>.json per signal
  - YamlDuckdbSink: writes factors/<dir>/factor.{yaml,duckdb} (101 alphas style)
  - BatchSummarySink: writes output_dir/multi_alpha_*.json + .md at batch end

In PR6, `PaperPipeline._process_one_signal` will:
  1. Call codegen + backtest → FactorResult
  2. Dispatch `result` to every Sink in `recipe.sinks`
  3. After all signals done, call `sinks[*].write_batch(results)` for sinks
     that need end-of-batch aggregation (BatchSummarySink).

Usage:
    from llmwikify.reproduction.sink import (
        Sink, SingleJsonSink, YamlDuckdbSink, BatchSummarySink,
    )
    sinks = [
        SingleJsonSink(output_dir=Path("scripts/output")),
        YamlDuckdbSink(factors_dir=Path("quant/factors"), strategy_dir="my_paper"),
        BatchSummarySink(output_dir=Path("scripts/output"), paper_id="my_paper"),
    ]
"""
from __future__ import annotations

from .base import Sink
from .batch_summary import BatchSummarySink
from .single_json import SingleJsonSink
from .yaml_duckdb import YamlDuckdbSink

__all__ = [
    "Sink",
    "SingleJsonSink",
    "YamlDuckdbSink",
    "BatchSummarySink",
]
