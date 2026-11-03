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

#: Sentinel pattern that never matches — stands in for "no pattern applies".
_NEVER = re.compile(r"(?!x)x")


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

        # Page names carry a directory prefix ("concepts/Risk Parity") while
        # prose usually says "Risk Parity" — both forms count as a mention.
        # A title shared by two pages is ambiguous, so only the fully
        # qualified form may match for those.
        title_to_page: dict[str, str] = {}
        ambiguous: set[str] = set()
        for page_name in existing_pages:
            title = page_name.rsplit("/", 1)[-1]
            if title in title_to_page and title_to_page[title] != page_name:
                ambiguous.add(title)
            else:
                title_to_page[title] = page_name

        # Precompute: strip wikilinks + lowercase once per page.
        # Pairwise check uses a C-level substring test before regex —
        # avoids O(N²) re.search (150s → seconds on 1400-page wikis).
        stripped: dict[str, str] = {}
        linked: dict[str, set[str]] = {}
        for page_name, content in pages.items():
            targets: set[str] = set()
            for link in re.findall(r"\[\[(.*?)\]\]", content):
                target = wiki._parse_wikilink_target(link)
                if target in skip_names:
                    continue
                # Accept both link forms: "Gold" and "concepts/Gold".
                targets.add(target)
                targets.add(title_to_page.get(target, target))
            linked[page_name] = targets
            stripped[page_name] = re.sub(r"\[\[.*?\]\]", "", content).lower()

        # Compile patterns once; skip names too short for meaningful matching.
        candidates = sorted(
            c
            for c in existing_pages
            if len(c.rsplit("/", 1)[-1]) >= 3 and not c.startswith("Query:")
        )
        title_patterns: dict[str, re.Pattern] = {}
        path_patterns: dict[str, re.Pattern] = {}
        for c in candidates:
            title = c.rsplit("/", 1)[-1]
            if title not in ambiguous:
                title_patterns[c] = re.compile(r"\b" + re.escape(title) + r"\b", re.IGNORECASE)
            if "/" in c:
                path_patterns[c] = re.compile(r"\b" + re.escape(c) + r"\b", re.IGNORECASE)

        for page_name, content_text_l in stripped.items():
            page_links = linked[page_name]
            for candidate in candidates:
                if candidate == page_name or candidate in page_links:
                    continue
                title = candidate.rsplit("/", 1)[-1]
                title_l = title.lower()
                path_l = candidate.lower()
                if title_l not in content_text_l and path_l not in content_text_l:
                    continue
                title_hit = title_patterns.get(candidate, _NEVER).search(content_text_l)
                path_hit = path_patterns.get(candidate, _NEVER).search(content_text_l)
                if title_hit or path_hit:
                    concept_mentions.setdefault(candidate, []).append(page_name)

        for concept, pages_list in sorted(
            concept_mentions.items(), key=lambda x: -len(x[1])
        ):
            if len(pages_list) >= MIN_MISSING_REF_COUNT:
                results.append(
                    {
                        "type": self.name,
                        "concept": concept,
                        "concept_title": concept.rsplit("/", 1)[-1],
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
