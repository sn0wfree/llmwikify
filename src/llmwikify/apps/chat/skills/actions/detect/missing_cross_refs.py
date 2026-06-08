"""detect_missing_cross_refs_skill — find concepts mentioned but not wikilinked.

One of the 8 detect actions (Phase 5 item #20) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a concept mentioned in 2+ pages but not
yet wikilinked to its entity/concept page.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectMissingCrossRefsSkill(DetectActionSkill):
    """Find concepts mentioned in 2+ pages but not wikilinked."""

    name = "detect_missing_cross_refs"
    description = "Find concepts mentioned in 2+ pages but not wikilinked"
    DETECT_METHOD = "_detect_missing_cross_refs"
    DETECT_DESC = (
        "Find concepts that appear in 2+ pages but are not "
        "yet wikilinked. Suggests auto-linking candidates."
    )


detect_missing_cross_refs_skill = DetectMissingCrossRefsSkill()


__all__ = ["DetectMissingCrossRefsSkill", "detect_missing_cross_refs_skill"]
