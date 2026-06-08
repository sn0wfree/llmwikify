"""detect_outdated_pages_skill — find pages that may be outdated.

One of the 8 detect actions (Phase 5 item #17) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a page whose source data is older than
expected (e.g. a stock price from 2 years ago, a
statistic from 5 years ago).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectOutdatedPagesSkill(DetectActionSkill):
    """Detect pages that may be outdated based on source dates."""

    name = "detect_outdated_pages"
    description = "Detect pages that may be outdated based on source dates"
    DETECT_METHOD = "_detect_outdated_pages"
    DETECT_DESC = (
        "Find pages whose content is older than expected "
        "based on the freshness of their underlying sources. "
        "Useful for prioritizing re-research."
    )


detect_outdated_pages_skill = DetectOutdatedPagesSkill()


__all__ = ["DetectOutdatedPagesSkill", "detect_outdated_pages_skill"]
