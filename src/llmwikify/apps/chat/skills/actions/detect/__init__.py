"""detect/ — 8 detect actions (Phase 5 items 15-22).

Per ``v0.32-skill-restructure.md`` §3.1, the 8 detect
actions are extracted from ``apps/research/analyzer.py``
(``_detect_*`` methods). They are orchestrated by:

  - ``lint_skill`` (the wiki health check)
  - ``wiki_query_skill.wiki_knowledge_gaps`` (future)

Each detect action is a thin wrapper over
``Wiki._detect_*()``; the common plumbing lives in
``_base.py::DetectActionSkill``.

Public API
----------

  - ``detect_knowledge_gaps_skill`` (item #15)
  - ``detect_data_gaps_skill``         (item #16)
  - ``detect_outdated_pages_skill``    (item #17)
  - ``detect_dated_claims_skill``      (item #18)
  - ``detect_query_page_overlap_skill``(item #19)
  - ``detect_missing_cross_refs_skill``(item #20)
  - ``detect_potential_contradictions_skill`` (item #21)
  - ``detect_redundancy_skill``        (item #22)
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.detect.dated_claims import detect_dated_claims_skill
from llmwikify.apps.chat.skills.actions.detect.data_gaps import detect_data_gaps_skill
from llmwikify.apps.chat.skills.actions.detect.knowledge_gaps import (
    detect_knowledge_gaps_skill,
)
from llmwikify.apps.chat.skills.actions.detect.missing_cross_refs import (
    detect_missing_cross_refs_skill,
)
from llmwikify.apps.chat.skills.actions.detect.outdated_pages import (
    detect_outdated_pages_skill,
)
from llmwikify.apps.chat.skills.actions.detect.potential_contradictions import (
    detect_potential_contradictions_skill,
)
from llmwikify.apps.chat.skills.actions.detect.query_page_overlap import (
    detect_query_page_overlap_skill,
)
from llmwikify.apps.chat.skills.actions.detect.redundancy import detect_redundancy_skill


ALL_DETECT_SKILLS = [
    detect_knowledge_gaps_skill,
    detect_data_gaps_skill,
    detect_outdated_pages_skill,
    detect_dated_claims_skill,
    detect_query_page_overlap_skill,
    detect_missing_cross_refs_skill,
    detect_potential_contradictions_skill,
    detect_redundancy_skill,
]


__all__ = [
    "detect_knowledge_gaps_skill",
    "detect_data_gaps_skill",
    "detect_outdated_pages_skill",
    "detect_dated_claims_skill",
    "detect_query_page_overlap_skill",
    "detect_missing_cross_refs_skill",
    "detect_potential_contradictions_skill",
    "detect_redundancy_skill",
    "ALL_DETECT_SKILLS",
]
