"""detect_redundancy_skill — find redundant or overlapping content.

One of the 8 detect actions (Phase 5 item #22) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a pair of pages or sections with high
content overlap (potential merge candidates).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectRedundancySkill(DetectActionSkill):
    """Find potentially redundant or overlapping content."""

    name = "detect_redundancy"
    description = "Find potentially redundant or overlapping content"
    DETECT_METHOD = "_detect_redundancy"
    DETECT_DESC = (
        "Find pages or sections with high content overlap. "
        "Candidates for merging or cross-linking."
    )


detect_redundancy_skill = DetectRedundancySkill()


__all__ = ["DetectRedundancySkill", "detect_redundancy_skill"]
