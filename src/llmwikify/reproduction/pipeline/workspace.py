"""Workspace — manages stage registry and execution for a project root."""
from __future__ import annotations

import logging
from typing import Any

from .config import WorkspaceConfig
from .stages.base import Stage, StageContext

logger = logging.getLogger(__name__)


class Workspace:
    """Manages a set of named stages bound to a workspace directory.

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
        """Execute requested stages in order.

        Args:
            stage_names: Subset of stages to run.  ``None`` runs all.
            ctx: Optional pre-built context.  One is created if omitted.

        Returns:
            The final StageContext after all stages have run.
        """
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
