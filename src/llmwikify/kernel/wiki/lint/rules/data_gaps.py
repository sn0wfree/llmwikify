"""Rule: detect data gaps (unsourced claims, vague temporal references)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...constants import (
    MAX_CONTRADICTIONS,
    MAX_SUMMARY_ITEMS,
    MIN_ASSERTION_LENGTH,
    MIN_ASSERTIONS_FOR_GAP,
)
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class DataGapsRule(Rule):
    """Detect potential data gaps in wiki pages.

    Detects two flavors of gap:
    1. ``unsourced_claims`` — pages with many assertions but no
       ``## Sources`` section and no inline citations
    2. ``vague_temporal`` — pages that use vague time words
       ("recently", "nowadays", "last year", etc.)

    Extracted from ``WikiAnalyzer._detect_data_gaps``. Behavior is
    preserved.
    """

    name = "data_gap"
    max_results = MAX_CONTRADICTIONS

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        has_sources_section = bool(re.search(r'^#{1,3}\s+Sources', content, re.MULTILINE | re.IGNORECASE))
        has_inline_citations = bool(re.search(r'\[Source[^\]]*\]\(', content))

        lines = content.split('\n')
        assertion_lines = [
            line.strip() for line in lines
            if line.strip()
            and not line.startswith('#')
            and not line.startswith('---')
            and not line.startswith('[')
            and len(line.strip()) > MIN_ASSERTION_LENGTH
        ]

        if len(assertion_lines) >= MIN_ASSERTIONS_FOR_GAP and not has_sources_section and not has_inline_citations:
            results.append({
                "type": "unsourced_claims",
                "page": page_name,
                "assertion_count": len(assertion_lines),
                "observation": (
                    f"'{page_name}' contains {len(assertion_lines)} assertion(s) "
                    f"without cited sources"
                ),
            })

        vague_time_words = re.findall(
            r'\b(recently|soon|upcoming|former|previous|last year|next year|in the past|currently|nowadays|these days)\b',
            content, re.IGNORECASE
        )
        if vague_time_words:
            results.append({
                "type": "vague_temporal",
                "page": page_name,
                "vague_references": list({w.lower() for w in vague_time_words})[:MAX_SUMMARY_ITEMS],
                "observation": (
                    f"'{page_name}' uses vague temporal references: "
                    f"{', '.join({w.lower() for w in vague_time_words[:3]})}"
                ),
            })
