"""plan_skill — research planning (sub-queries).

Thin wrapper over the LLM-driven planner in
``apps/research/engine.py``. Generates sub-queries that
guide the gather step.

  Action: ``plan(query)``
  Returns: ``{"sub_queries": list[dict], "rationale": str}``

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.

Implementation note: the planner is a thin wrapper around
LLM call. The actual LLM-driven logic lives in
``engine.py:_action_plan``; here we just dispatch to it.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _plan(args: dict, ctx: SkillContext) -> SkillResult:
    """Generate sub-queries for a research query.

    Reads from the engine's LLM-driven planner.
    """
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    # TODO: wire to engine._action_plan in Phase 6.
    # For Phase 5, return a minimal plan placeholder so the
    # action is callable; the real planner integration is
    # Phase 6's research_skill work.
    return SkillResult.ok({
        "sub_queries": [
            {"q": query, "rationale": "primary"},
        ],
        "rationale": f"plan for: {query}",
    })


class PlanSkill(Skill):
    """Action wrapper for research planning."""

    name = "plan"
    description = "Plan sub-queries for a research query"
    actions = {
        "plan": SkillAction(
            name="plan",
            description=(
                "Generate 3-5 sub-queries that decompose the input "
                "query. The output guides the gather step (each "
                "sub-query is searched and filtered independently)."
            ),
            handler=_plan,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research query"},
                },
                "required": ["query"],
            },
        ),
    }


plan_skill = PlanSkill()


__all__ = ["PlanSkill", "plan_skill"]
