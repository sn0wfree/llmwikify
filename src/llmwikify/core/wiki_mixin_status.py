"""Wiki status mixin — wiki status reporting, orphan detection config."""

import logging

from .wiki_analyzer import WikiAnalyzer

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiStatusMixin(WikiProtocol):
    """Wiki status reporting and orphan detection configuration."""

    def _should_exclude_orphan(self, page_name: str, page_path) -> bool:
        """Check if a page should be excluded from orphan detection."""
        import re
        page_name_lower = page_name.lower()

        for pattern in self._default_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        for pattern in self._user_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        if page_path.exists():
            content = page_path.read_text()
            for key in self._exclude_frontmatter_keys:
                if f"{key}:" in content:
                    return True

        try:
            rel_path = page_path.relative_to(self.wiki_dir)
            for part in rel_path.parts:
                if part.lower() in self._archive_dirs:
                    return True
        except ValueError:
            pass

        return False

    def status(self) -> dict:
        """Get wiki status."""
        result = {
            "initialized": self.is_initialized(),
            "root": str(self.root),
            "page_count": len(self._wiki_pages()),
            "source_count": len([f for f in self.raw_dir.rglob("*") if f.is_file()]),
            "indexed_pages": self.index.get_page_count() if self.is_initialized() else "N/A",
            "total_links": self.index.get_link_count() if self.is_initialized() else "N/A",
        }

        pages_by_type = {}
        for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
            sub_path = self.wiki_dir / subdir
            if sub_path.exists():
                pages_by_type[subdir] = sorted(
                    str(p.relative_to(self.wiki_dir))[:-3]
                    for p in sub_path.rglob("*.md")
                )
        root_pages = [
            str(p.relative_to(self.wiki_dir))[:-3]
            for p in self.wiki_dir.glob("*.md")
            if p.stem not in ("index", "log")
        ]
        if root_pages:
            pages_by_type["root"] = sorted(root_pages)
        result["pages_by_type"] = pages_by_type

        if self.is_initialized():
            try:
                engine = self.get_relation_engine()
                stats = engine.get_stats()
                result["graph_stats"] = stats
            except Exception:
                logger.warning("Failed to load graph stats")
                result["graph_stats"] = {"total_relations": 0, "unique_concepts": 0}

        return result

    def recommend(self) -> dict:
        """Generate smart recommendations.

        Delegates to WikiAnalyzer — single source of truth.
        """
        return WikiAnalyzer(self).recommend()

    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement.

        Deprecated: Use `lint(format="brief")` instead.
        """
        import warnings
        warnings.warn(
            "hint() is deprecated; use wiki.lint(format='brief') instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return WikiAnalyzer(self)._generate_hints()
