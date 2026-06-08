"""detect_knowledge_gaps_skill — find knowledge gaps in the wiki.

One of the 8 detect actions (Phase 5 item #15) extracted
from ``apps/research/analyzer.py`` (via the
``WikiAnalyzer._detect_knowledge_gaps`` method).

The action returns ``{"findings": list[dict]}`` where
each finding is a knowledge gap (e.g. uncovered topic,
missing entity link, sparse data point).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect._base import DetectActionSkill


class DetectKnowledgeGapsSkill(DetectActionSkill):
    """Detect knowledge gaps across the wiki."""

    name = "detect_knowledge_gaps"
    description = "Find knowledge gaps across the wiki"
    DETECT_METHOD = "_detect_knowledge_gaps"
    DETECT_DESC = (
        "Find knowledge gaps across the wiki: topics with "
        "no coverage, entities mentioned but not defined, "
        "or pages with sparse content."
    )


detect_knowledge_gaps_skill = DetectKnowledgeGapsSkill()


__all__ = ["DetectKnowledgeGapsSkill", "detect_knowledge_gaps_skill"]
