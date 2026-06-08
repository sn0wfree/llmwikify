"""Pipeline skills — Phase 12: multi-step orchestration.

Per ``v0.32-execution-plan.md`` Phase 12, pipeline skills
are extracted from ``research_skill.py`` (Phase 6) to become
standalone, independently callable skills.

Pipelines compose actions via direct Python calls (NOT
through the LLM), per the Unix philosophy (``docs/designs/
principles/unix-philosophy.md``).

Current pipelines (v0.32.5):

  1. ``gather_skill`` — search/extract sources for sub-queries
     (extracted from ``research_skill._act_gather``)
  2. ``report_skill`` — write final markdown report from
     synthesis + sources (extracted from ``research_skill._act_report``)

These pipelines can be called:

  - **by research_skill** — internal composition (the 7-step
    ReAct loop calls gather/report as steps)
  - **by the LLM** — as standalone tools (e.g. "gather
    sources for X" without a full research session)
  - **by wiki_query_skill** — as part of the 28-action
    aggregator (Phase 12, wiki_query)
"""

from llmwikify.apps.chat.skills.pipelines.gather_skill import (
    GatherSkill,
    gather_skill,
)
from llmwikify.apps.chat.skills.pipelines.report_skill import (
    ReportSkill,
    report_skill,
)

__all__ = [
    "GatherSkill",
    "gather_skill",
    "ReportSkill",
    "report_skill",
]
