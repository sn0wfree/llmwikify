"""Rule: detect knowledge gaps (orphan concepts, isolated source pages)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llmwikify.kernel.storage.backend import is_path_excluded

from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki

logger = logging.getLogger(__name__)


class KnowledgeGapsRule(Rule):
    """Detect knowledge gaps across the wiki.

    Detects:
    - ``unreferenced_entity`` — concepts in the knowledge graph
      that have no wiki page
    - ``isolated_source`` — source pages with no wikilinks

    Extracted from ``WikiAnalyzer._detect_knowledge_gaps``. Behavior
    is preserved.
    """

    name = "knowledge_gap"

    def run(self, wiki: "Wiki") -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []

        if not wiki.wiki_dir.exists():
            return gaps

        # 1. Orphan concepts from the relation engine
        try:
            engine = wiki.get_relation_engine()
            orphan_concepts = engine.find_orphan_concepts()
            for concept in orphan_concepts[:3]:
                gaps.append({
                    "type": "unreferenced_entity",
                    "concept": concept,
                    "observation": f"'{concept}' is in the knowledge graph but has no wiki page",
                    "suggestion": f"Consider creating a page for '{concept}'",
                })
        except Exception as e:
            logger.warning("Relation engine orphan detection failed: %s", e)

        # 2. Isolated source pages
        import re
        sources_dir = wiki.wiki_dir / "sources"
        if sources_dir.exists():
            for source_page in sources_dir.rglob("*.md"):
                if is_path_excluded(source_page):
                    continue
                page_name = wiki._page_display_name(source_page)
                content = source_page.read_text()
                wikilinks = re.findall(r'\[\[(.*?)\]\]', content)
                if not wikilinks:
                    gaps.append({
                        "type": "isolated_source",
                        "page": page_name,
                        "observation": f"Source page '{page_name}' has no wikilinks to other pages",
                        "suggestion": "Consider adding cross-references to related concepts/entities",
                    })

                if len(gaps) >= 3:
                    break

        return gaps[:3]
