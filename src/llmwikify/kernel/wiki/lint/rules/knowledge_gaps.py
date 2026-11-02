"""Rule: detect knowledge gaps (orphan concepts, isolated source pages)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .. import Rule

if TYPE_CHECKING:
    from ...snapshot import PageSnapshot
    from ...wiki import Wiki

logger = logging.getLogger(__name__)

# The source summary pages live in ``<wiki_dir>/sources``; they are part
# of the page snapshot (their display name is ``sources/<name>``).
_SOURCES_DIR_NAME = "sources"


class KnowledgeGapsRule(Rule):
    """Detect knowledge gaps across the wiki.

    Detects:
    - ``unreferenced_entity`` — concepts in the knowledge graph
      that have no wiki page
    - ``isolated_source`` — source pages with no wikilinks

    Extracted from ``WikiAnalyzer._detect_knowledge_gaps``. Behavior
    is preserved.

    The source candidate set is the same in both paths -- with and
    without a page snapshot: it comes from ``wiki._wiki_pages()``, so
    the two public interfaces of this rule can not diverge.
    """

    name = "knowledge_gap"
    max_results = 3

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        if not wiki.wiki_dir.exists():
            return []

        gaps: list[dict[str, Any]] = []

        # 1. Orphan concepts from the relation engine (global check)
        gaps.extend(self._orphan_concept_gaps(wiki))

        # 2. Isolated source pages (per-directory check)
        for page_name, content in self._source_pages_from_disk(wiki):
            self._collect_isolated_source(gaps, page_name, content)
            if len(gaps) >= self.max_results:
                break

        return gaps[: self.max_results]

    def run_with_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run this rule against ``wiki``, taking the source pages from a snapshot.

        The source summary pages live under ``<wiki_dir>/sources`` and are
        therefore part of the page snapshot: their content is read from
        the snapshot instead of from disk. The read is lossy (utf-8 with
        ``errors="replace"``) in both paths, so a source page that is not
        valid UTF-8 no longer kills this rule (residual risk R1 of the
        P4-a design).
        """
        if snapshot is None:
            return self.run(wiki)

        if not wiki.wiki_dir.exists():
            return []

        gaps: list[dict[str, Any]] = []

        # 1. Orphan concepts from the relation engine (global check)
        gaps.extend(self._orphan_concept_gaps(wiki))

        # 2. Isolated source pages (per-directory check)
        for page_name, content in self._source_pages_from_snapshot(wiki, snapshot):
            self._collect_isolated_source(gaps, page_name, content)
            if len(gaps) >= self.max_results:
                break

        return gaps[: self.max_results]

    def _orphan_concept_gaps(self, wiki: Wiki) -> list[dict[str, Any]]:
        """Concepts in the relation engine that have no wiki page."""
        gaps: list[dict[str, Any]] = []
        try:
            engine = wiki.get_relation_engine()
            orphan_concepts = engine.find_orphan_concepts()
            for concept in orphan_concepts[:3]:
                gaps.append(
                    {
                        "type": "unreferenced_entity",
                        "concept": concept,
                        "observation": f"'{concept}' is in the knowledge graph but has no wiki page",
                        "suggestion": f"Consider creating a page for '{concept}'",
                    }
                )
        except Exception as e:
            logger.warning("Relation engine orphan detection failed: %s", e)
        return gaps

    def _source_pages_from_disk(self, wiki: Wiki):
        """Yield ``(page_name, content)`` of the source pages, read from disk.

        The candidates are the pages of ``wiki._wiki_pages()`` that live
        under ``<wiki_dir>/sources`` -- the very enumeration (and the
        very order) the snapshot path uses.  Both paths therefore see
        exactly the same source pages, so the two public interfaces of
        this rule (``wiki._detect_knowledge_gaps()`` and ``lint()``)
        can not report different issues for the same wiki.

        ``_wiki_pages()`` applies the stem exclusion (``index`` /
        ``log``), the ``.sink`` exclusion and ``is_path_excluded``; a
        source summary page named ``index.md`` / ``log.md`` is therefore
        not checked any more (design section 14, R-4).
        """
        sources_dir = wiki.wiki_dir / _SOURCES_DIR_NAME
        if not sources_dir.exists():
            return
        for source_page in wiki._wiki_pages():
            if not source_page.is_relative_to(sources_dir):
                continue
            page_name = wiki._page_display_name(source_page)
            yield page_name, source_page.read_text(encoding="utf-8", errors="replace")

    def _source_pages_from_snapshot(self, wiki: Wiki, snapshot: PageSnapshot):
        """Yield ``(page_name, content)`` of the source pages, from the snapshot.

        The source pages are part of the snapshot (they live under
        ``<wiki_dir>/sources``); a page that did not fit into the memory
        budget is read back from disk.
        """
        sources_dir = wiki.wiki_dir / _SOURCES_DIR_NAME
        for name in snapshot.names:
            if not snapshot.path_of(name).is_relative_to(sources_dir):
                continue
            content = snapshot.content_of(name)
            if content is None:
                # Degraded page: it did not fit into the snapshot, read
                # it back from disk (same read as the legacy path).
                content = snapshot.path_of(name).read_text(
                    encoding="utf-8", errors="replace"
                )
            yield name, content

    def _collect_isolated_source(
        self, gaps: list[dict[str, Any]], page_name: str, content: str
    ) -> None:
        """Report a source page that does not link to any other page."""
        wikilinks = re.findall(r"\[\[(.*?)\]\]", content)
        if not wikilinks:
            gaps.append(
                {
                    "type": "isolated_source",
                    "page": page_name,
                    "observation": f"Source page '{page_name}' has no wikilinks to other pages",
                    "suggestion": "Consider adding cross-references to related concepts/entities",
                }
            )
