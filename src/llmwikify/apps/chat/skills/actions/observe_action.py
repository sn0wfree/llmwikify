"""observe_skill — ReAct observation (interpret the new state).

  Action: ``observe_research_state(state)``
  Returns: ``{"observations": list[str]}``

Invoked by the framework in the Observe step of every
ReAct round. The observations are appended to the
state's ``observations`` list, which the LLM sees in the
next round's reasoning prompt.

This is one of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1. The actual logic was
extracted from ``apps/research/engine.py::_observe`` (71
lines in the design doc).

The Phase 5 implementation provides a **rule-based
observer** that emits 4 categories of observations:
  1. Source count by type
  2. Failed sub-queries
  3. Wiki vs web ratio
  4. Knowledge gap alerts
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


def _observe_research_state(state: dict) -> list[str]:
    """Pure-function observer. Returns a list of observation strings."""
    observations: list[str] = []
    sources = state.get("sources", []) or []
    sub_queries = state.get("sub_queries", []) or []
    synthesis = state.get("synthesis")

    # 1. Source count by type
    if sources:
        type_counts = Counter(s.get("source_type", "unknown") for s in sources)
        type_summary = ", ".join(
            f"{t}={c}" for t, c in sorted(type_counts.items())
        )
        observations.append(f"Source types: {type_summary} (total {len(sources)})")

    # 2. Failed sub-queries
    failed = [sq for sq in sub_queries if isinstance(sq, dict) and sq.get("status") == "failed"]
    if failed:
        titles = [sq.get("query", "?")[:40] for sq in failed[:3]]
        observations.append(
            f"⚠ {len(failed)} sub-queries failed: {titles}"
        )

    # 3. Wiki vs web ratio
    wiki_count = sum(1 for s in sources if s.get("source_type") == "wiki")
    web_count = sum(1 for s in sources if s.get("source_type") == "web")
    if wiki_count + web_count > 0:
        observations.append(f"Local wiki: {wiki_count}, Web: {web_count}")

    # 4. Knowledge gap alert
    if synthesis and isinstance(synthesis, dict):
        gaps = synthesis.get("knowledge_gaps", [])
        if isinstance(gaps, list) and len(gaps) > 3:
            observations.append(
                f"⚠ {len(gaps)} knowledge gaps may impact report completeness"
            )

    return observations


async def _observe(args: dict, ctx: SkillContext) -> SkillResult:
    state = args.get("state", {})
    if not isinstance(state, dict):
        return SkillResult.fail("state must be a dict")
    observations = _observe_research_state(state)
    return SkillResult.ok({"observations": observations})


class ObserveSkill(Skill):
    """Action wrapper for ReAct observation."""

    name = "observe"
    description = "ReAct observation: interpret state into human-readable observations"
    actions = {
        "observe_research_state": SkillAction(
            name="observe_research_state",
            description=(
                "Take a research state dict and return a list of "
                "interpreted observations (source type counts, "
                "failed sub-queries, wiki/web ratio, gap alerts). "
                "Invoked by the framework in the Observe step of "
                "every ReAct round."
            ),
            handler=_observe,
            input_schema={
                "type": "object",
                "properties": {
                    "state": {
                        "type": "object",
                        "description": "Current research state",
                    },
                },
                "required": ["state"],
            },
        ),
    }


observe_skill = ObserveSkill()


__all__ = ["ObserveSkill", "observe_skill", "_observe_research_state"]
