"""HarnessService — facade over the 6 eval primitives (v0.33.0).

Per v0.33-service-refactor.md, this is one of the 5+1
services. It exposes the existing eval classes in
``apps/chat/harness/`` as a single injection point.

The 6 eval classes:
  - QualityGate         (gates research output)
  - SourceFilter        (filters sources)
  - StructureValidator  (validates markdown structure)
  - ResearchReviewer    (reviews research quality)
  - ResearchRevisor     (revises research)
  - SourceAnalyzer      (analyzes sources)
"""

from __future__ import annotations

import logging
from functools import cached_property
from typing import Any

logger = logging.getLogger(__name__)


class HarnessService:
    """Facade over apps/chat/harness/ (6 eval primitives).

    Each primitive is constructed lazily on first access.
    The ``config`` parameter is shared across all primitives.
    """

    def __init__(
        self,
        config: Any = None,
        wiki: Any = None,
        session_manager: Any = None,
        llm: Any = None,
        report_llm: Any = None,
    ):
        self.config = config
        self.wiki = wiki
        self.session_manager = session_manager
        self.llm = llm
        self.report_llm = report_llm

    # ─── Lazy property accessors ─────────────────────────────

    @cached_property
    def quality_gate(self) -> Any:
        from llmwikify.apps.research.harness.quality_gate import (
            QualityGate,
        )

        return QualityGate(self.config)

    @cached_property
    def source_filter(self) -> Any:
        from llmwikify.apps.research.harness.source_filter import (
            SourceFilter,
        )

        return SourceFilter(self.config)

    @cached_property
    def structure_validator(self) -> Any:
        from llmwikify.apps.research.harness.structure_validator import (
            StructureValidator,
        )

        return StructureValidator()

    @cached_property
    def research_reviewer(self) -> Any:
        from llmwikify.apps.research.harness.review import (
            ResearchReviewer,
        )

        return ResearchReviewer(
            wiki=self.wiki,
            llm_client=self.llm,
            config=self.config,
        )

    @cached_property
    def research_revisor(self) -> Any:
        from llmwikify.apps.research.harness.review import (
            ResearchRevisor,
        )

        return ResearchRevisor(
            wiki=self.wiki,
            llm_client=self.report_llm or self.llm,
            config=self.config,
        )

    @cached_property
    def source_analyzer(self) -> Any:
        from llmwikify.apps.research.harness.source_analyzer import (
            SourceAnalyzer,
        )

        return SourceAnalyzer(
            wiki=self.wiki,
            session_manager=self.session_manager,
            config=self.config,
        )

    def reset(self) -> None:
        """Drop cached primitives (for tests)."""
        for name in (
            "quality_gate",
            "source_filter",
            "structure_validator",
            "research_reviewer",
            "research_revisor",
            "source_analyzer",
        ):
            self.__dict__.pop(name, None)


__all__ = ["HarnessService"]
