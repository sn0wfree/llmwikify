"""DEPRECATED: use llmwikify.reproduction.core.stage instead.

This module re-exports `Stage` and `StageContext` from `core.stage` for
backward compatibility with code that imported them from the old
`pipeline.stages.base` location.

Migration:
    # Old
    from llmwikify.reproduction.pipeline.stages.base import Stage, StageContext
    # New
    from llmwikify.reproduction.core import Stage, StageContext

See docs/designs/run_101_alphas_v2_design.md §17 for the PR1-PR7 refactor plan.
"""
from __future__ import annotations

import warnings

from llmwikify.reproduction.core.stage import Stage, StageContext

warnings.warn(
    "llmwikify.reproduction.pipeline.stages.base is deprecated. "
    "Use llmwikify.reproduction.core.stage (or core.Stage / core.StageContext).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Stage", "StageContext"]
