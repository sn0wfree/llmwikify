"""Rule: detect Query: pages with high keyword overlap."""

from __future__ import annotations

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
    from ...snapshot import PageSnapshot
    from ...wiki import Wiki


class QueryPageOverlapRule(Rule):
    """Find Query: pages with >=85% keyword Jaccard overlap.

    Extracted from ``WikiAnalyzer._detect_query_page_overlap``.
    Behavior is preserved.
    """

    name = "topic_overlap"
    max_results = MAX_QUERY_OVERLAP_HINTS

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        if not wiki.wiki_dir.exists():
            return []

        query_pages = []
        for page in wiki.wiki_dir.rglob("*.md"):
            if ".sink" in str(page):
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
                query_pages.append(
                    {
                        "page_name": page_name,
                        "keywords": keywords,
                        "file": str(page),
                    }
                )

        results: list[dict[str, Any]] = []
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
                        results.append(
                            {
                                "type": self.name,
                                "page_a": p1["page_name"],
                                "page_b": p2["page_name"],
                                "jaccard_score": round(jaccard, 3),
                                "shared_keywords": sorted(
                                    p1["keywords"] & p2["keywords"]
                                ),
                                "observation": (
                                    f"'{p1['page_name']}' and '{p2['page_name']}' share {len(p1['keywords'] & p2['keywords'])} keywords "
                                    f"(Jaccard: {jaccard:.0%}). They may cover overlapping topics."
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

        Without a snapshot the legacy path runs unchanged. With a
        snapshot the query pages come from the snapshot instead of from
        a second walk over the wiki directory -- the comparison itself is
        the one of ``run``, verbatim.
        """
        if snapshot is None:
            return self.run(wiki)

        if not wiki.wiki_dir.exists():
            return []

        query_pages = self._query_pages_from_snapshot(snapshot)

        results: list[dict[str, Any]] = []
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
                        results.append(
                            {
                                "type": self.name,
                                "page_a": p1["page_name"],
                                "page_b": p2["page_name"],
                                "jaccard_score": round(jaccard, 3),
                                "shared_keywords": sorted(
                                    p1["keywords"] & p2["keywords"]
                                ),
                                "observation": (
                                    f"'{p1['page_name']}' and '{p2['page_name']}' share {len(p1['keywords'] & p2['keywords'])} keywords "
                                    f"(Jaccard: {jaccard:.0%}). They may cover overlapping topics."
                                ),
                            }
                        )

            if len(results) >= self.max_results:
                break

        return results[: self.max_results]

    def _query_pages_from_snapshot(
        self, snapshot: PageSnapshot
    ) -> list[dict[str, Any]]:
        """The query pages of the snapshot, in the shape of the legacy path.

        The rule looks at the **file stem** of a page, not at its display
        name: ``Query: foo.bar`` and ``Query: foo`` are two different
        pages and only the stem tells them apart (``Path("foo.bar")``
        has the stem ``foo``). The stem therefore comes from
        ``snapshot.path_of(name).stem`` -- the path of the page on disk,
        exactly like the legacy path.

        The legacy path enumerates ``wiki.wiki_dir.rglob("*.md")`` while
        the snapshot enumerates ``wiki._wiki_pages()``: the difference
        are the pages named ``index.md`` / ``log.md``, which
        ``_wiki_pages()`` leaves out. Neither of them can start with
        ``Query:``, so the set of query pages -- and with it the issues
        -- does not change.

        The ``.sink`` and ``is_path_excluded`` filters are not applied
        again: ``_wiki_pages()`` has already applied them, so the pages
        of the snapshot are filtered.

        Platform note: on Windows the path codec writes the full width
        colon (``Query：foo.md``), so ``stem.startswith("Query:")`` is
        never true there and the rule stays dead code on that platform.
        The snapshot path reproduces this verbatim -- the stem comes
        from the same file name.
        """
        query_pages: list[dict[str, Any]] = []
        for name in snapshot.names:
            page = snapshot.path_of(name)
            page_name = page.stem
            if not page_name.startswith("Query:"):
                continue

            keywords = {
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in STOP_WORDS and len(w) > MIN_KEYWORD_LENGTH
            }

            if keywords:
                query_pages.append(
                    {
                        "page_name": page_name,
                        "keywords": keywords,
                        "file": str(page),
                    }
                )
        return query_pages
