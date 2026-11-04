"""Rule: detect pages with similar/overlapping names (potential redundancy)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class RedundancyRule(Rule):
    """Detect potentially redundant or overlapping content.

    Detects pages whose names share a substring (one is a prefix
    or substring of the other), suggesting they may cover the
    same topic and could be merged.

    Extracted from ``WikiAnalyzer._detect_redundancy``. Behavior
    is preserved.
    """

    name = "redundancy"
    max_results = 2

    def run(
        self, wiki: Wiki, pages: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        # Keeps its own walk: the original iterates ``_wiki_pages()``,
        # which still includes Query: pages (the shared map excludes them).
        del pages
        if not wiki.wiki_dir.exists():
            return []
        page_names = [wiki._page_display_name(p) for p in wiki._wiki_pages()]
        if not page_names:
            return []

        results: list[dict[str, Any]] = []

        # Lower-case once: the comparison below used to re-lower both
        # names on every pair, which is O(pairs) string allocations.
        lowered = [name.lower() for name in page_names]

        for i, name1 in enumerate(page_names):
            low1 = lowered[i]
            for j in range(i + 1, len(page_names)):
                name2 = page_names[j]
                low2 = lowered[j]
                if low1 in low2 or low2 in low1:
                    if len(name1) > 5 and len(name2) > 5:
                        results.append(
                            {
                                "type": "similar_page_names",
                                "page_a": name1,
                                "page_b": name2,
                                "observation": (
                                    f"Pages '{name1}' and '{name2}' have similar names. "
                                    f"Consider merging if they cover the same topic."
                                ),
                            }
                        )

            if len(results) >= self.max_results:
                break

        return results[: self.max_results]
