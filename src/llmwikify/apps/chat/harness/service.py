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
from typing import Any

logger = logging.getLogger(__name__)


class HarnessService:
    """Facade over apps/chat/harness/ (6 eval primitives).

    Each primitive is constructed lazily on first access.
    The ``config`` parameter is shared across all primitives.
    """

    def __init__(self, config: Any = None, wiki: Any = None,
                 session_manager: Any = None, llm: Any = None,
                 report_llm: Any = None):
        self.config = config
        self.wiki = wiki
        self.session_manager = session_manager
        self.llm = llm
        self.report_llm = report_llm

        # Lazy-initialized primitives
        self._quality_gate = None
        self._source_filter = None
        self._structure_validator = None
        self._research_reviewer = None
        self._research_revisor = None
        self._source_analyzer = None

    # ─── Lazy property accessors ─────────────────────────────

    @property
    def quality_gate(self) -> Any:
        if self._quality_gate is None:
            from llmwikify.apps.chat.harness.quality_gate import (
                QualityGate,
            )
            self._quality_gate = QualityGate(self.config)
        return self._quality_gate

    @property
    def source_filter(self) -> Any:
        if self._source_filter is None:
            from llmwikify.apps.chat.harness.source_filter import (
                SourceFilter,
            )
            self._source_filter = SourceFilter(self.config)
        return self._source_filter

    @property
    def structure_validator(self) -> Any:
        if self._structure_validator is None:
            from llmwikify.apps.chat.harness.structure_validator import (
                StructureValidator,
            )
            self._structure_validator = StructureValidator()
        return self._structure_validator

    @property
    def research_reviewer(self) -> Any:
        if self._research_reviewer is None:
            from llmwikify.apps.chat.harness.review import (
                ResearchReviewer,
            )
            self._research_reviewer = ResearchReviewer(
                wiki=self.wiki,
                llm_client=self.llm,
                config=self.config,
            )
        return self._research_reviewer

    @property
    def research_revisor(self) -> Any:
        if self._research_revisor is None:
            from llmwikify.apps.chat.harness.review import (
                ResearchRevisor,
            )
            self._research_revisor = ResearchRevisor(
                wiki=self.wiki,
                llm_client=self.report_llm or self.llm,
                config=self.config,
            )
        return self._research_revisor

    @property
    def source_analyzer(self) -> Any:
        if self._source_analyzer is None:
            from llmwikify.apps.chat.harness.source_analyzer import (
                SourceAnalyzer,
            )
            self._source_analyzer = SourceAnalyzer(
                wiki=self.wiki,
                session_manager=self.session_manager,
                config=self.config,
            )
        return self._source_analyzer

    def reset(self) -> None:
        """Reset all cached primitives (for tests)."""
        self._quality_gate = None
        self._source_filter = None
        self._structure_validator = None
        self._research_reviewer = None
        self._research_revisor = None
        self._source_analyzer = None


__all__ = ["HarnessService"]
