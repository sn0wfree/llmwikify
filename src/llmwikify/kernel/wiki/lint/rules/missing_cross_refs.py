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
        skip_names = {wiki._index_page_name, wiki._log_page_name}

        # Precompute: strip wikilinks + lowercase once per page.
        # Pairwise check uses a C-level substring test before regex —
        # avoids O(N²) re.search (150s → seconds on 1400-page wikis).
        stripped: dict[str, str] = {}
        wikilink_sets: dict[str, set[str]] = {}
        for page_name, content in pages.items():
            wikilinks: set[str] = set()
            for link in re.findall(r"\[\[(.*?)\]\]", content):
                target = wiki._parse_wikilink_target(link)
                if target not in skip_names:
                    wikilinks.add(target)
            wikilink_sets[page_name] = wikilinks
            stripped[page_name] = re.sub(r"\[\[.*?\]\]", "", content).lower()

        # Compile patterns once; skip names too short for meaningful matching.
        candidates = sorted(
            c for c in existing_pages if len(c) >= 3 and not c.startswith("Query:")
        )
        patterns = {
            c: re.compile(r"\b" + re.escape(c) + r"\b", re.IGNORECASE)
            for c in candidates
        }

        for page_name, content_text_l in stripped.items():
            wikilinks = wikilink_sets[page_name]
            for candidate in candidates:
                if candidate == page_name or candidate in wikilinks:
                    continue
                if candidate.lower() not in content_text_l:
                    continue
                if patterns[candidate].search(content_text_l):
                    concept_mentions.setdefault(candidate, []).append(page_name)

        for concept, pages_list in sorted(
            concept_mentions.items(), key=lambda x: -len(x[1])
        ):
            if len(pages_list) >= MIN_MISSING_REF_COUNT:
                results.append(
                    {
                        "type": self.name,
                        "concept": concept,
                        "mentioning_pages": pages_list[:MAX_MISSING_DISPLAY],
                        "mention_count": len(pages_list),
                        "observation": (
                            f"'{concept}' is mentioned in {len(pages_list)} pages ({', '.join(pages_list[:3])}"
                            f"{'...' if len(pages_list) > 3 else ''}) but not linked. "
                            f"Consider adding [[{concept}]] wikilinks."
                        ),
                    }
                )

            if len(results) >= self.max_results:
                break
