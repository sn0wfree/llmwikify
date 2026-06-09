"""Rule: detect Query: pages with high keyword overlap."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from llmwikify.kernel.storage.backend import is_path_excluded

from ...constants import (
    JACCARD_OVERLAP_THRESHOLD,
    MAX_QUERY_OVERLAP_HINTS,
    MIN_KEYWORD_LENGTH,
    STOP_WORDS,
)
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class QueryPageOverlapRule(Rule):
    """Find Query: pages with >=85% keyword Jaccard overlap.

    Extracted from ``WikiAnalyzer._detect_query_page_overlap``.
    Behavior is preserved.
    """

    name = "topic_overlap"

    def run(self, wiki: "Wiki") -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        if not wiki.wiki_dir.exists():
            return hints

        query_pages = []
        for page in wiki.wiki_dir.rglob("*.md"):
            if '.sink' in str(page):
                continue
            if is_path_excluded(page):
                continue
            page_name = page.stem
            if not page_name.startswith("Query:"):
                continue

            keywords = {
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in STOP_WORDS and len(w) > MIN_KEYWORD_LENGTH
            }

            if keywords:
                query_pages.append({
                    "page_name": page_name,
                    "keywords": keywords,
                    "file": str(page),
                })

        seen_pairs = set()
        for i in range(len(query_pages)):
            for j in range(i + 1, len(query_pages)):
                p1 = query_pages[i]
                p2 = query_pages[j]

                union = len(p1["keywords"] | p2["keywords"])
                if union == 0:
                    continue

                overlap = len(p1["keywords"] & p2["keywords"])
                jaccard = overlap / union

                if jaccard >= JACCARD_OVERLAP_THRESHOLD:
                    pair_key = tuple(sorted([p1["page_name"], p2["page_name"]]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        hints.append({
                            "type": self.name,
                            "page_a": p1["page_name"],
                            "page_b": p2["page_name"],
                            "jaccard_score": round(jaccard, 3),
                            "shared_keywords": sorted(p1["keywords"] & p2["keywords"]),
                            "observation": (
                                f"'{p1['page_name']}' and '{p2['page_name']}' share {len(p1['keywords'] & p2['keywords'])} keywords "
                                f"(Jaccard: {jaccard:.0%}). They may cover overlapping topics."
                            ),
                        })

            if len(hints) >= MAX_QUERY_OVERLAP_HINTS:
                break

        return hints[:MAX_QUERY_OVERLAP_HINTS]
