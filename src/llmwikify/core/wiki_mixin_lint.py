"""Wiki lint mixin — health check, lint detection, delegating to WikiAnalyzer."""

import logging

logger = logging.getLogger(__name__)


class WikiLintMixin:
    """Lint/health check methods — thin delegation layer to WikiAnalyzer."""

    def _detect_dated_claims(self) -> list[dict]:
        """Find year mentions in pages that predate latest raw source by 3+ years."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_dated_claims()

    def _detect_query_page_overlap(self) -> list[dict]:
        """Find Query: pages with >=85% keyword Jaccard overlap."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_query_page_overlap()

    def _detect_missing_cross_refs(self) -> list[dict]:
        """Find concepts mentioned in 2+ pages but not wikilinked."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_missing_cross_refs()

    def _detect_potential_contradictions(self) -> list[dict]:
        """Scan wiki pages for potential contradictions."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_potential_contradictions()

    def _detect_data_gaps(self) -> list[dict]:
        """Detect potential data gaps in wiki pages."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_data_gaps()

    def _detect_outdated_pages(self) -> list[dict]:
        """Detect pages that may be outdated based on source dates."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_outdated_pages()

    def _detect_knowledge_gaps(self) -> list[dict]:
        """Detect knowledge gaps across the wiki."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_knowledge_gaps()

    def _detect_redundancy(self) -> list[dict]:
        """Detect potentially redundant or overlapping content."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_redundancy()

    def lint(
        self,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        generate_investigations: bool = False,
    ) -> dict:
        """Health check the wiki with schema-aware gap detection."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self).lint(
            mode=mode, limit=limit, force=force,
            generate_investigations=generate_investigations,
        )

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._generate_hints()
