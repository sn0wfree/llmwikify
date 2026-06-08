"""detect_data_gaps_skill — find data gaps in wiki pages.

One of the 8 detect actions (Phase 5 item #16) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding represents a missing data point (e.g. a page
that asserts a fact without source, or a chart that has
no underlying data).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectDataGapsSkill(DetectActionSkill):
    """Detect data gaps in wiki pages."""

    name = "detect_data_gaps"
    description = "Detect data gaps in wiki pages (unsourced claims, missing data)"
    DETECT_METHOD = "_detect_data_gaps"
    DETECT_DESC = (
        "Detect data gaps in wiki pages: claims without "
        "sources, tables without underlying data, or "
        "assertions that need verification."
    )


detect_data_gaps_skill = DetectDataGapsSkill()


__all__ = ["DetectDataGapsSkill", "detect_data_gaps_skill"]
