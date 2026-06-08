"""filter_skill — source filtering (dedupe + evidence scoring).

  Action: ``filter(sources, min_score)``
  Returns: ``{"filtered": list[dict], "dropped": int}``

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.

Dedupes by URL; drops sources below ``min_score`` (default 0.3).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _filter(args: dict, ctx: SkillContext) -> SkillResult:
    sources = args.get("sources", [])
    if not isinstance(sources, list):
        return SkillResult.fail("sources must be a list")
    min_score = args.get("min_score", 0.3)
    seen_urls: set[str] = set()
    out: list[dict] = []
    dropped = 0
    for s in sources:
        if not isinstance(s, dict):
            dropped += 1
            continue
        url = s.get("url", "")
        score = s.get("score", 0.5)
        if url in seen_urls:
            dropped += 1
            continue
        if score < min_score:
            dropped += 1
            continue
        seen_urls.add(url)
        out.append(s)
    return SkillResult.ok({"filtered": out, "dropped": dropped})


class FilterSkill(Skill):
    """Action wrapper for source filtering (dedupe + evidence scoring)."""

    name = "filter"
    description = "Filter sources by URL dedup + minimum evidence score"
    actions = {
        "filter": SkillAction(
            name="filter",
            description=(
                "Given a list of source dicts, dedupe by URL and "
                "drop sources below min_score (default 0.3). "
                "Returns the kept sources and the count of dropped."
            ),
            handler=_filter,
            input_schema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of source dicts to filter",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum evidence score to keep (default 0.3)",
                        "default": 0.3,
                    },
                },
                "required": ["sources"],
            },
        ),
    }


filter_skill = FilterSkill()


__all__ = ["FilterSkill", "filter_skill"]
