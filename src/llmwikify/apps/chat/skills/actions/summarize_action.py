"""summarize_skill — multi-source synthesis (core claims).

Thin wrapper over the LLM-driven synthesizer in
``apps/research/synthesizer.py``.

  Action: ``summarize(sources)``
  Returns: ``{"claims": list[dict], "narrative": str}``

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _summarize(args: dict, ctx: SkillContext) -> SkillResult:
    """Synthesize core claims from a list of source dicts."""
    sources = args.get("sources", [])
    if not sources:
        return SkillResult.fail("sources list is required (non-empty)")
    # TODO: wire to engine._action_synthesize in Phase 6.
    # For Phase 5, return a minimal synthesis placeholder.
    return SkillResult.ok({
        "claims": [
            {"text": f"Key claim from {len(sources)} source(s)", "confidence": 0.7},
        ],
        "narrative": f"Synthesis of {len(sources)} source(s).",
    })


class SummarizeSkill(Skill):
    """Action wrapper for multi-source synthesis."""

    name = "summarize"
    description = "Synthesize core claims from a list of sources"
    actions = {
        "summarize": SkillAction(
            name="summarize",
            description=(
                "Given a list of source dicts (from gather), extract "
                "core claims and produce a narrative synthesis. "
                "Returns {claims: [...], narrative: str}."
            ),
            handler=_summarize,
            input_schema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of source dicts to synthesize",
                    },
                },
                "required": ["sources"],
            },
        ),
    }


summarize_skill = SummarizeSkill()


__all__ = ["SummarizeSkill", "summarize_skill"]
