"""Rule: detect pages with year claims older than the latest source."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ...constants import (
    MAX_DATED_CLAIM_HINTS,
    MIN_YEAR_THRESHOLD,
    YEAR_GAP_THRESHOLD,
)
from .. import Rule, _is_query_page

if TYPE_CHECKING:
    from ...snapshot import PageSnapshot
    from ...wiki import Wiki


class DatedClaimsRule(Rule):
    """Find year mentions in pages that predate the latest raw source by 3+ years.

    Extracted from ``WikiAnalyzer._detect_dated_claims``. Behavior
    is preserved byte-for-byte (modulo the ``type`` field, which
    is now the rule's ``name``).
    """

    # The rule reads its pages in its own way, so it owns
    # run_with_snapshot() as well.
    snapshot_mode = "custom"

    name = "dated_claim"
    max_results = MAX_DATED_CLAIM_HINTS

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        current_year = datetime.now(timezone.utc).year

        latest_source_year = self._scan_latest_source_year(wiki)
        if latest_source_year == 0:
            return []

        self._latest_source_year = latest_source_year
        self._current_year = current_year
        return super().run(wiki)

    def run_with_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run this rule against ``wiki``, taking the pages from a snapshot.

        The raw scan is *not* part of the snapshot (the raw directory is
        not a wiki page directory), so it runs exactly as in ``run``.
        The page bodies come from the snapshot instead of from disk.
        """
        if snapshot is None:
            return self.run(wiki)

        current_year = datetime.now(timezone.utc).year

        latest_source_year = self._scan_latest_source_year(wiki)
        if latest_source_year == 0:
            return []

        self._latest_source_year = latest_source_year
        self._current_year = current_year
        return self._detect_pages(wiki, snapshot)

    def _scan_latest_source_year(self, wiki: Wiki) -> int:
        """The newest year mentioned by the raw sources (0 when there is none).

        The raw directory is read directly: it is not part of the page
        snapshot.
        """
        latest_source_year = 0
        if wiki.raw_dir.exists():
            for src in wiki.raw_dir.rglob("*"):
                if not src.is_file():
                    continue
                content = wiki._backend.read_file(wiki._logical(src)) or ""
                years = re.findall(r"\b(20\d{2})\b", content)
                if years:
                    latest_source_year = max(
                        latest_source_year, max(int(y) for y in years)
                    )
        return latest_source_year

    def _detect_pages(self, wiki: Wiki, snapshot: PageSnapshot) -> list[dict[str, Any]]:
        """The per-page template of ``Rule.run``, with the pages from a snapshot.

        Same pages, same order, same cut-off as the legacy path: the
        display names of the snapshot (``Query:`` pages skipped), the
        content from the snapshot and a fallback read for the pages
        that did not fit into the memory budget.
        """
        if not wiki.wiki_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for name in snapshot.names:
            if _is_query_page(name):
                continue
            content = snapshot.content_of(name)
            if content is None:
                # Degraded page: it did not fit into the snapshot, read
                # it back from disk (same read as the legacy path).
                content = wiki._backend.get_page(name) or ""
            self.detect(name, content, wiki, results)
            if len(results) >= self.max_results:
                break
        return results[: self.max_results]

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        years_in_page = re.findall(r"\b(20\d{2})\b", content)

        for year_str in years_in_page:
            year = int(year_str)
            if MIN_YEAR_THRESHOLD <= year <= self._current_year - YEAR_GAP_THRESHOLD:
                if self._latest_source_year - year >= YEAR_GAP_THRESHOLD:
                    results.append(
                        {
                            "type": self.name,
                            "page": page_name,
                            "file": str(
                                wiki.wiki_dir / f"{page_name.replace('/', '_')}.md"
                            ),
                            "claim_year": year,
                            "latest_source_year": self._latest_source_year,
                            "gap_years": self._latest_source_year - year,
                            "observation": (
                                f"'{page_name}' references {year}, but the latest raw source is from {self._latest_source_year}. "
                                f"The gap is {self._latest_source_year - year} years. "
                                f"Content may be outdated."
                            ),
                        }
                    )
                    break
