"""PipelineRunner — thin orchestrator that drives stages through Workspace."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import WorkspaceConfig

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Aggregated result of a pipeline run."""

    stages_completed: list[str] = field(default_factory=list)
    stages_failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class PipelineRunner:
    """Thin wrapper that executes a sequence of stages via Workspace.

    Args:
        config: WorkspaceConfig governing paths and limits.
    """

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self.config = config or WorkspaceConfig()

    def run(self, stage_names: list[str] | None = None) -> PipelineResult:
        """Execute the requested stages (stub — returns empty result).

        Args:
            stage_names: Optional list of stage names to run.  When *None*,
                         all registered stages are executed.

        Returns:
            PipelineResult with completion status.
        """
        logger.info(
            "PipelineRunner.run called (workspace=%s, stages=%s)",
            self.config.workspace_path,
            stage_names,
        )
        return PipelineResult()
