"""Stage abstract base + StageContext — legacy stage registry primitives.

These existed in `llmwikify.reproduction.pipeline.stages.base` and
`llmwikify.reproduction.pipeline.workspace`. They are preserved here for
backward compatibility (re-exported from the old path).

In the new framework (`PaperPipeline` + `PaperRecipe`), the per-paper flow is
driven by composition of `SignalSource` / `BacktestEngine` / `Sink` rather than
explicit `Stage.execute()` calls. `Stage` / `StageContext` remain available
for callers that registered stages via the old `Workspace` pattern.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    """Mutable context passed through stage execution (legacy).

    New code should prefer `PaperRecipe` + `PaperPipeline` for paper-level
    flows. This dataclass is preserved for backward compatibility with
    `Workspace.execute()`.
    """

    workspace_path: Any = None
    alpha_indices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Stage(ABC):
    """Abstract base class for pipeline stages (legacy).

    Subclasses must set ``name`` and implement ``execute``.
    """

    name: str = "unnamed"

    @abstractmethod
    def execute(self, ctx: StageContext) -> StageContext:
        """Run this stage, returning an (optionally mutated) context."""
        ...
