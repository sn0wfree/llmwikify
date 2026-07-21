"""Rule: detect pages that may be outdated based on source dates."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ...constants import MAX_CONTRADICTIONS, OUTDATED_YEAR_GAP
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class OutdatedPagesRule(Rule):
    """Detect pages that may be outdated based on source dates.

    Extracted from ``WikiAnalyzer._detect_outdated_pages``.
    Behavior is preserved.
    """

    name = "potentially_outdated"
    max_results = MAX_CONTRADICTIONS

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        current_year = datetime.now(timezone.utc).year

        source_refs = re.findall(r'\(raw/([^)]+)\)', content)
        if source_refs:
            years_in_page = re.findall(r'\b(20\d{2})\b', content)
            if years_in_page:
                latest_year = max(int(y) for y in years_in_page)
                if current_year - latest_year >= OUTDATED_YEAR_GAP:
                    results.append({
                        "type": self.name,
                        "page": page_name,
                        "latest_year_mentioned": latest_year,
                        "current_year": current_year,
                        "observation": (
                            f"'{page_name}' references {latest_year} as latest date. "
                            f"May need review with newer sources."
                        ),
                    })
