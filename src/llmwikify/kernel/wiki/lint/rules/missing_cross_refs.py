"""Rule: detect concepts mentioned in 2+ pages but not wikilinked."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...constants import (
    MAX_CROSS_REF_HINTS,
    MAX_MISSING_DISPLAY,
    MIN_MISSING_REF_COUNT,
)
from .. import CrossPageRule

if TYPE_CHECKING:
    from ...wiki import Wiki


class MissingCrossRefsRule(CrossPageRule):
    """Find concepts mentioned in 2+ pages but not wikilinked.

    Extracted from ``WikiAnalyzer._detect_missing_cross_refs``.
    Behavior is preserved.
    """

    name = "missing_cross_ref"
    max_results = MAX_CROSS_REF_HINTS

    def detect_all(
        self,
        pages: dict[str, str],
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        existing_pages = set(pages.keys())
        concept_mentions: dict[str, list[str]] = {}

        for page_name, content in pages.items():
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

        for concept, pages_list in sorted(concept_mentions.items(), key=lambda x: -len(x[1])):
            if len(pages_list) >= MIN_MISSING_REF_COUNT:
                results.append({
                    "type": self.name,
                    "concept": concept,
                    "mentioning_pages": pages_list[:MAX_MISSING_DISPLAY],
                    "mention_count": len(pages_list),
                    "observation": (
                        f"'{concept}' is mentioned in {len(pages_list)} pages ({', '.join(pages_list[:3])}"
                        f"{'...' if len(pages_list) > 3 else ''}) but not linked. "
                        f"Consider adding [[{concept}]] wikilinks."
                    ),
                })

            if len(results) >= self.max_results:
                break
