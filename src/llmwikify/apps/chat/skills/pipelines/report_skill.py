"""report_skill — pipeline: write final markdown report.

Per ``v0.32-execution-plan.md`` Phase 12: this pipeline is
extracted from ``research_skill._act_report`` (Phase 6) to
become a standalone, independently callable skill.

Pipeline structure
------------------

  1. Build a markdown report from:
     - ``query`` (the research query)
     - ``synthesis`` (cross-source claims + narrative)
     - ``sources`` (collected source dicts)
     - ``knowledge_gaps`` (optional, from analyze step)
  2. Return the report as markdown

Can be called:

  - **by research_skill** — as the "report" step in the
    7-step ReAct loop
  - **by the LLM** — as a standalone tool ("generate a
    report from these sources")
  - **by wiki_query_skill** — as part of the 28-action
    aggregator

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#25)
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Action handler ───────────────────────────────────────────────


async def _generate_report(args: dict, ctx: SkillContext) -> SkillResult:
    """Generate a markdown report from synthesis + sources.

    ``args`` keys:

      - ``query`` (str): the research query (used as title)
      - ``synthesis`` (dict, optional): must contain
        ``"narrative"`` (str) and ``"claims"`` (list[dict]).
      - ``sources`` (list[dict]): source dicts with at
        least ``"url"`` and ``"title"`` keys.
      - ``knowledge_gaps`` (list[str], optional): gaps
        identified during analysis.

    Returns:

      - ``report_md`` (str): the full markdown report
      - ``report_length`` (int): character count
    """
    query = args.get("query", "Research Report")
    synthesis = args.get("synthesis") or {}
    sources = args.get("sources", [])
    knowledge_gaps = args.get("knowledge_gaps", [])

    # Build the markdown report
    lines: list[str] = [
        f"# {query}",
        "",
        "## Summary",
        synthesis.get("narrative", "(no synthesis)"),
        "",
        "## Key Claims",
    ]

    for claim in synthesis.get("claims", []):
        text = claim.get("text", "") if isinstance(claim, dict) else str(claim)
        lines.append(f"- {text}")

    lines.extend(["", "## Sources", ""])
    for s in sources:
        title = s.get("title", s.get("url", "?"))
        url = s.get("url", "")
        lines.append(f"- [{title}]({url})")

    if knowledge_gaps:
        lines.extend([
            "",
            "## Knowledge Gaps",
            "",
            *[f"- {g}" for g in knowledge_gaps],
        ])

    report_md = "\n".join(lines)

    return SkillResult.ok({
        "report_md": report_md,
        "report_length": len(report_md),
    })


# ─── Skill declaration ─────────────────────────────────────────


class ReportSkill(Skill):
    """Pipeline: generate a markdown report from synthesis + sources.

    Can be called standalone ("generate a report from these
    sources") or composed by research_skill as its "report" step.
    """

    name = "report"
    description = (
        "Generate a markdown research report from synthesis "
        "narrative, claims, sources, and knowledge gaps."
    )
    actions = {
        "generate_report": SkillAction(
            name="generate_report",
            description=(
                "Build a markdown report with Summary, Key Claims, "
                "Sources, and Knowledge Gaps sections."
            ),
            handler=_generate_report,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Research query (used as report title)",
                    },
                    "synthesis": {
                        "type": "object",
                        "description": "Synthesis dict with 'narrative' and 'claims' keys",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Source dicts with 'url' and 'title' keys",
                    },
                    "knowledge_gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of identified knowledge gaps",
                    },
                },
                "required": [],
            },
        ),
    }


report_skill = ReportSkill()


__all__ = ["ReportSkill", "report_skill"]
