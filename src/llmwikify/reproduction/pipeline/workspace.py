"""DEPRECATED: Workspace stub kept for backward compatibility.

`Workspace` is the old stage-registry pattern. The new framework uses
`PaperPipeline` + `PaperRecipe` from `llmwikify.reproduction.core`.

This file is preserved (not removed) so that existing tests / scripts that
import `Workspace` continue to work. New code should use `PaperPipeline`.

See docs/designs/run_101_alphas_v2_design.md §17 for the PR1-PR7 refactor plan.
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

from llmwikify.reproduction.core.stage import Stage, StageContext

from .config import WorkspaceConfig

warnings.warn(
    "llmwikify.reproduction.pipeline.workspace.Workspace is deprecated. "
    "Use llmwikify.reproduction.core.PaperPipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


class Workspace:
    """Manages a set of named stages bound to a workspace directory.

    DEPRECATED: kept for backward compatibility. Use `PaperPipeline` for new code.

    Args:
        config: WorkspaceConfig providing paths and settings.
    """

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self.config = config or WorkspaceConfig()
        self._stages: dict[str, Stage] = {}

    def register(self, stage: Stage) -> None:
        """Register a Stage instance by its ``name``."""
        self._stages[stage.name] = stage
        logger.debug("Registered stage: %s", stage.name)

    def get_stage(self, name: str) -> Stage | None:
        """Return the registered Stage with *name*, or ``None``."""
        return self._stages.get(name)

    def list_stages(self) -> list[str]:
        """Return ordered list of registered stage names."""
        return list(self._stages.keys())

    def execute(
        self,
        stage_names: list[str] | None = None,
        ctx: StageContext | None = None,
    ) -> StageContext:
        """Execute requested stages in order (legacy)."""
        if ctx is None:
            ctx = StageContext(workspace_path=self.config.workspace_path)

        targets = stage_names or self.list_stages()
        for name in targets:
            stage = self._stages.get(name)
            if stage is None:
                logger.warning("Stage %r not registered, skipping", name)
                continue
            logger.info("Executing stage: %s", name)
            ctx = stage.execute(ctx)

        return ctx
