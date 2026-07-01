"""Core abstractions for the reproduction pipeline framework.

Public API:
  - Stage, StageContext     : legacy stage registry primitives (backward compat)
  - PaperRecipe              : configuration dataclass for one paper run
  - PaperPipeline            : driver that runs a PaperRecipe end-to-end

PR1 scope: framework skeleton only. Concrete SignalSource / BacktestEngine / Sink
implementations arrive in PR2-PR4.

Usage:
    from llmwikify.reproduction.core import PaperRecipe, PaperPipeline
    recipe = PaperRecipe(paper_id="...", signal_source=..., ...)
    pipeline = PaperPipeline(recipe)
    results = pipeline.run()
"""
from __future__ import annotations

from .pipeline import PaperPipeline
from .recipe import PaperRecipe
from .stage import Stage, StageContext

__all__ = [
    "Stage",
    "StageContext",
    "PaperRecipe",
    "PaperPipeline",
]
