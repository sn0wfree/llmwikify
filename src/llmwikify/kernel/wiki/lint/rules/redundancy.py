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

    def run(self, wiki: "Wiki") -> list[dict[str, Any]]:
        redundancy: list[dict[str, Any]] = []
        pages = wiki._wiki_pages()

        if not pages:
            return redundancy

        page_names = [wiki._page_display_name(p) for p in pages]
        for i, name1 in enumerate(page_names):
            for name2 in page_names[i+1:]:
                if (name1.lower() in name2.lower() or name2.lower() in name1.lower()):
                    if len(name1) > 5 and len(name2) > 5:
                        redundancy.append({
                            "type": "similar_page_names",
                            "page_a": name1,
                            "page_b": name2,
                            "observation": (
                                f"Pages '{name1}' and '{name2}' have similar names. "
                                f"Consider merging if they cover the same topic."
                            ),
                        })

            if len(redundancy) >= 2:
                break

        return redundancy[:2]
