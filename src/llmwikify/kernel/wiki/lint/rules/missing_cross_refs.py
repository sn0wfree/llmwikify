"""Rule: detect concepts mentioned in 2+ pages but not wikilinked."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...constants import (
    MAX_CROSS_REF_HINTS,
    MAX_MISSING_DISPLAY,
    MIN_MISSING_REF_COUNT,
)
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class MissingCrossRefsRule(Rule):
    """Find concepts mentioned in 2+ pages but not wikilinked.

    Extracted from ``WikiAnalyzer._detect_missing_cross_refs``.
    Behavior is preserved.
    """

    name = "missing_cross_ref"

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []

        if not wiki.wiki_dir.exists():
            return hints

        existing_pages = set()
        for page in wiki._wiki_pages():
            existing_pages.add(wiki._page_display_name(page))

        concept_mentions: dict[str, list[str]] = {}

        for page in wiki._wiki_pages():
            page_name = wiki._page_display_name(page)

            content = page.read_text()

            wikilinks = set()
            for link in re.findall(r'\[\[(.*?)\]\]', content):
                target = wiki._parse_wikilink_target(link)
                wikilinks.add(target)

            content_text = re.sub(r'\[\[.*?\]\]', '', content)

            for candidate in existing_pages:
                if candidate == page_name:
                    continue
                if candidate in wikilinks:
                    continue

                pattern = r'\b' + re.escape(candidate) + r'\b'
                if re.search(pattern, content_text, re.IGNORECASE):
                    if candidate not in concept_mentions:
                        concept_mentions[candidate] = []
                    concept_mentions[candidate].append(page_name)

        for concept, pages in sorted(concept_mentions.items(), key=lambda x: -len(x[1])):
            if len(pages) >= MIN_MISSING_REF_COUNT:
                hints.append({
                    "type": self.name,
                    "concept": concept,
                    "mentioning_pages": pages[:MAX_MISSING_DISPLAY],
                    "mention_count": len(pages),
                    "observation": (
                        f"'{concept}' is mentioned in {len(pages)} pages ({', '.join(pages[:3])}"
                        f"{'...' if len(pages) > 3 else ''}) but not linked. "
                        f"Consider adding [[{concept}]] wikilinks."
                    ),
                })

            if len(hints) >= MAX_CROSS_REF_HINTS:
                break

        return hints[:MAX_CROSS_REF_HINTS]
