"""detect_query_page_overlap_skill — find Query: pages with high overlap.

One of the 8 detect actions (Phase 5 item #19) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a pair of Query: pages with >=85%
keyword Jaccard overlap (per the original method).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectQueryPageOverlapSkill(DetectActionSkill):
    """Detect Query: pages with >=85% keyword Jaccard overlap."""

    name = "detect_query_page_overlap"
    description = "Find Query: pages with high keyword Jaccard overlap"
    DETECT_METHOD = "_detect_query_page_overlap"
    DETECT_DESC = (
        "Find Query: pages (research session results) with "
        ">=85% keyword Jaccard overlap. Useful for "
        "deduplicating similar research."
    )


detect_query_page_overlap_skill = DetectQueryPageOverlapSkill()


__all__ = ["DetectQueryPageOverlapSkill", "detect_query_page_overlap_skill"]
