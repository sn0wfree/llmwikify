"""detect_dated_claims_skill — find year mentions that may be stale.

One of the 8 detect actions (Phase 5 item #18) extracted
from ``apps/research/analyzer.py``.

The action returns ``{"findings": list[dict]}`` where
each finding is a year mention in a page that predates
the latest raw source by 3+ years (heuristic from the
original ``_detect_dated_claims`` method).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectDatedClaimsSkill(DetectActionSkill):
    """Detect year mentions in pages that predate latest raw source by 3+ years."""

    name = "detect_dated_claims"
    description = "Find year mentions in pages that may be stale"
    DETECT_METHOD = "_detect_dated_claims"
    DETECT_DESC = (
        "Find year mentions in pages that predate the latest "
        "raw source by 3+ years. Useful for flagging "
        "potentially stale claims."
    )


detect_dated_claims_skill = DetectDatedClaimsSkill()


__all__ = ["DetectDatedClaimsSkill", "detect_dated_claims_skill"]
