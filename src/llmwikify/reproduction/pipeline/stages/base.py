"""Stage abstract base class — every pipeline stage implements this."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    """Mutable context passed through stage execution."""

    workspace_path: Any = None
    alpha_indices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Stage(ABC):
    """Abstract base class for pipeline stages.

    Subclasses must set ``name`` and implement ``execute``.
    """

    name: str = "unnamed"

    @abstractmethod
    def execute(self, ctx: StageContext) -> StageContext:
        """Run this stage, returning an (optionally mutated) context.

        Args:
            ctx: Shared context that flows through the pipeline.

        Returns:
            The updated StageContext.
        """
