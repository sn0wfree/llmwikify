"""detect_potential_contradictions_skill — find potentially contradictory claims.

One of the 8 detect actions (Phase 5 item #21) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a pair of pages or claims that may
contradict each other (e.g. one says "X is true" and
another says "X is false", or numeric mismatches).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectPotentialContradictionsSkill(DetectActionSkill):
    """Find potentially contradictory claims in the wiki."""

    name = "detect_potential_contradictions"
    description = "Find potentially contradictory claims in the wiki"
    DETECT_METHOD = "_detect_potential_contradictions"
    DETECT_DESC = (
        "Scan wiki pages for potentially contradictory claims: "
        "binary oppositions (is/is not), numeric mismatches, "
        "or attribution conflicts."
    )


detect_potential_contradictions_skill = DetectPotentialContradictionsSkill()


__all__ = ["DetectPotentialContradictionsSkill", "detect_potential_contradictions_skill"]
