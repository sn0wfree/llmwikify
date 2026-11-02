"""Rule: detect pages with similar/overlapping names (potential redundancy)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import Rule

if TYPE_CHECKING:
    from ...snapshot import PageSnapshot
    from ...wiki import Wiki


class RedundancyRule(Rule):
    """Detect potentially redundant or overlapping content.

    Detects pages whose names share a substring (one is a prefix
    or substring of the other), suggesting they may cover the
    same topic and could be merged.

    Extracted from ``WikiAnalyzer._detect_redundancy``. Behavior
    is preserved.
    """

    # The rule reads its pages in its own way, so it owns
    # run_with_snapshot() as well.
    snapshot_mode = "custom"

    name = "redundancy"
    max_results = 2

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        pages = wiki._wiki_pages()
        if not pages:
            return []

        page_names = [wiki._page_display_name(p) for p in pages]
        results: list[dict[str, Any]] = []

        for i, name1 in enumerate(page_names):
            for name2 in page_names[i + 1 :]:
                if name1.lower() in name2.lower() or name2.lower() in name1.lower():
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

    def run_with_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run this rule against ``wiki``, taking the page names from a snapshot.

        The rule compares the **display names** of the pages. The
        snapshot carries exactly the names of ``wiki._wiki_pages()``
        (``wiki._page_display_name``), in the same order -- so the pairs
        and their order are the ones of the legacy path, and the second
        walk over the wiki directory goes away.

        Without a snapshot the legacy path runs unchanged.
        """
        if snapshot is None:
            return self.run(wiki)

        page_names = list(snapshot.names)
        if not page_names:
            return []

        results: list[dict[str, Any]] = []

        for i, name1 in enumerate(page_names):
            for name2 in page_names[i + 1 :]:
                if name1.lower() in name2.lower() or name2.lower() in name1.lower():
                    if len(name1) > 5 and len(name2) > 5:
                        results.append(
                            {
                                "type": "similar_page_names",
                                "page_a": name1,
                                "page_b": name2,
                                "observation": (
                                    f"Pages '{name1}' and '{name2}' have similar names. "
                                    "Consider merging if they cover the same topic."
                                ),
                            }
                        )

            if len(results) >= self.max_results:
                break

        return results[: self.max_results]
