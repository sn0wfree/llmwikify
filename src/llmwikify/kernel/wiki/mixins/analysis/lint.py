"""Wiki lint mixin — health check, lint detection, delegating to cached WikiAnalyzer.

Phase 2 #4 — the analyzer is cached on ``Wiki.__init__`` as
``self._analyzer``. Every method here is a 1-line delegate;
no per-call instantiation.
"""

import logging

from ...protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiLintMixin(WikiProtocol):
    """Lint/health check methods — thin delegation layer to the cached WikiAnalyzer."""

    def _detect_dated_claims(self) -> list[dict]:
        """Find year mentions in pages that predate latest raw source by 3+ years."""
        result: list[dict] = self._analyzer._detect_dated_claims()
        return result

    def _detect_query_page_overlap(self) -> list[dict]:
        """Find Query: pages with >=85% keyword Jaccard overlap."""
        result: list[dict] = self._analyzer._detect_query_page_overlap()
        return result

    def _detect_missing_cross_refs(self) -> list[dict]:
        """Find concepts mentioned in 2+ pages but not wikilinked."""
        result: list[dict] = self._analyzer._detect_missing_cross_refs()
        return result

    def _detect_potential_contradictions(self) -> list[dict]:
        """Scan wiki pages for potential contradictions."""
        result: list[dict] = self._analyzer._detect_potential_contradictions()
        return result

    def _detect_data_gaps(self) -> list[dict]:
        """Detect potential data gaps in wiki pages."""
        result: list[dict] = self._analyzer._detect_data_gaps()
        return result

    def _detect_outdated_pages(self) -> list[dict]:
        """Detect pages that may be outdated based on source dates."""
        result: list[dict] = self._analyzer._detect_outdated_pages()
        return result

    def _detect_knowledge_gaps(self) -> list[dict]:
        """Detect knowledge gaps across the wiki (fingerprint-cached)."""
        result: list[dict] = self._analyzer._detect_knowledge_gaps_cached()
        return result

    def _detect_redundancy(self) -> list[dict]:
        """Detect potentially redundant or overlapping content."""
        result: list[dict] = self._analyzer._detect_redundancy()
        return result

    def lint(
        self,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        generate_investigations: bool = False,
    ) -> dict:
        """Health check the wiki with schema-aware gap detection."""
        result: dict = self._analyzer.lint(
            mode=mode,
            limit=limit,
            force=force,
            generate_investigations=generate_investigations,
        )
        return result

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        result: dict = self._analyzer._generate_hints()
        return result
