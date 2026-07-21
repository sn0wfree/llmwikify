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
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class DatedClaimsRule(Rule):
    """Find year mentions in pages that predate the latest raw source by 3+ years.

    Extracted from ``WikiAnalyzer._detect_dated_claims``. Behavior
    is preserved byte-for-byte (modulo the ``type`` field, which
    is now the rule's ``name``).
    """

    name = "dated_claim"
    max_results = MAX_DATED_CLAIM_HINTS

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        current_year = now.year

        latest_source_year = 0
        if wiki.raw_dir.exists():
            for src in wiki.raw_dir.rglob("*"):
                if not src.is_file():
                    continue
                content = src.read_text(errors="ignore")
                years = re.findall(r'\b(20\d{2})\b', content)
                if years:
                    latest_source_year = max(
                        latest_source_year, max(int(y) for y in years)
                    )

        if latest_source_year == 0:
            return []

        self._latest_source_year = latest_source_year
        self._current_year = current_year
        return super().run(wiki)

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        years_in_page = re.findall(r'\b(20\d{2})\b', content)

        for year_str in years_in_page:
            year = int(year_str)
            if MIN_YEAR_THRESHOLD <= year <= self._current_year - YEAR_GAP_THRESHOLD:
                if self._latest_source_year - year >= YEAR_GAP_THRESHOLD:
                    results.append({
                        "type": self.name,
                        "page": page_name,
                        "file": str(wiki.wiki_dir / f"{page_name.replace('/', '_')}.md"),
                        "claim_year": year,
                        "latest_source_year": self._latest_source_year,
                        "gap_years": self._latest_source_year - year,
                        "observation": (
                            f"'{page_name}' references {year}, but the latest raw source is from {self._latest_source_year}. "
                            f"The gap is {self._latest_source_year - year} years. "
                            f"Content may be outdated."
                        ),
                    })
                    break
