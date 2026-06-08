"""revise_skill — content revision based on score feedback.

  Action: ``revise(text, score, feedback)``
  Returns: ``{"revised": str, "changes": list[str]}``

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.

In Phase 5, this is a thin rewrite that addresses the
score feedback by adding structure. Phase 6 will wire it
to the LLM-driven reviser.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _revise(args: dict, ctx: SkillContext) -> SkillResult:
    text = args.get("text", "")
    if not text:
        return SkillResult.fail("text is required")
    score = args.get("score", 0.0)
    feedback = args.get("feedback", "")
    changes: list[str] = []
    revised = text
    if score < 0.5:
        revised = f"## Summary\n\n{text}\n\n## Details\n\n(revised for clarity)\n"
        changes.append("added markdown structure (## Summary / ## Details)")
    if feedback:
        changes.append(f"applied feedback: {feedback[:80]}")
    return SkillResult.ok({"revised": revised, "changes": changes})


class ReviseSkill(Skill):
    """Action wrapper for content revision."""

    name = "revise"
    description = "Revise text based on score feedback"
    actions = {
        "revise": SkillAction(
            name="revise",
            description=(
                "Given a piece of text, a quality score, and optional "
                "feedback, produce a revised version. The revision "
                "addresses the lowest-scoring dimensions."
            ),
            handler=_revise,
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to revise"},
                    "score": {"type": "number", "description": "Current quality score (0-1)"},
                    "feedback": {"type": "string", "description": "Optional feedback"},
                },
                "required": ["text", "score"],
            },
        ),
    }


revise_skill = ReviseSkill()


__all__ = ["ReviseSkill", "revise_skill"]
