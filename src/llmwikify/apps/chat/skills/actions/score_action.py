"""score_skill — quality scoring (multi-dimensional).

  Action: ``score(text, dimensions)``
  Returns: ``{"score": float, "by_dimension": dict[str, float]}``

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1. The actual scoring
heuristic lives in ``apps/chat/quality_gate.py``.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _score(args: dict, ctx: SkillContext) -> SkillResult:
    text = args.get("text", "")
    if not text:
        return SkillResult.fail("text is required")
    # Multi-dimensional scoring: length, structure, citations.
    # Phase 5 placeholder; Phase 6 wires to LLM-based scorer.
    text_len = len(text)
    by_dimension: dict[str, float] = {
        "length": min(1.0, text_len / 5000.0),
        "structure": 0.5 if "##" in text else 0.2,
        "citations": 0.7 if "[[Source:" in text or "http" in text else 0.3,
    }
    avg = sum(by_dimension.values()) / max(1, len(by_dimension))
    return SkillResult.ok({
        "score": round(avg, 3),
        "by_dimension": by_dimension,
    })


class ScoreSkill(Skill):
    """Action wrapper for multi-dimensional quality scoring."""

    name = "score"
    description = "Multi-dimensional quality scoring (length, structure, citations)"
    actions = {
        "score": SkillAction(
            name="score",
            description=(
                "Score a piece of text on 3 dimensions: length "
                "(longer is better, capped at 5000 chars), structure "
                "(markdown sections), and citations (presence of "
                "[[Source:...]] markers or http links). Returns a "
                "weighted average score in [0, 1]."
            ),
            handler=_score,
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to score (markdown, plain, etc.)",
                    },
                    "dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of dimensions to score (default: all)",
                    },
                },
                "required": ["text"],
            },
        ),
    }


score_skill = ScoreSkill()


__all__ = ["ScoreSkill", "score_skill"]
