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

    def run(self, wiki: "Wiki") -> list[dict[str, Any]]:
        outdated: list[dict[str, Any]] = []
        current_year = datetime.now(timezone.utc).year

        if not wiki.wiki_dir.exists():
            return outdated

        for page in wiki._wiki_pages():
            page_name = wiki._page_display_name(page)
            if page_name.startswith("Query:"):
                continue

            content = page.read_text()

            source_refs = re.findall(r'\(raw/([^)]+)\)', content)
            if source_refs:
                years_in_page = re.findall(r'\b(20\d{2})\b', content)
                if years_in_page:
                    latest_year = max(int(y) for y in years_in_page)
                    if current_year - latest_year >= OUTDATED_YEAR_GAP:
                        outdated.append({
                            "type": self.name,
                            "page": page_name,
                            "latest_year_mentioned": latest_year,
                            "current_year": current_year,
                            "observation": (
                                f"'{page_name}' references {latest_year} as latest date. "
                                f"May need review with newer sources."
                            ),
                        })

            if len(outdated) >= MAX_CONTRADICTIONS:
                break

        return outdated[:MAX_CONTRADICTIONS]
