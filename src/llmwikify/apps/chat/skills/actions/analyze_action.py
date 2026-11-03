"""analyze_skill — source analysis + entity recognition.

Thin wrapper over ``Wiki.analyze_source(source_path, force)``.

  Action: ``analyze(source_path, force)``
  Returns: ``dict`` (the underlying Wiki method's return value)

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions._helpers import safe_call_async, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

#: Ceiling for the whole analysis chain (several LLM calls in sequence).
ANALYZE_TIMEOUT_SECONDS = 600.0


async def _analyze(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    source_path = args.get("source_path", "")
    force = args.get("force", False)
    # analyze_source drives the LLM synchronously; run it in a worker
    # thread so a slow completion cannot stall the event loop.
    return await safe_call_async(
        wiki.analyze_source,
        source_path,
        force=force,
        error_prefix="analyze failed",
        timeout=ANALYZE_TIMEOUT_SECONDS,
    )


class AnalyzeSkill(Skill):
    """Action wrapper for source analysis + entity recognition."""

    name = "analyze"
    description = "Analyze a source file (entities, structure, key points)"
    actions = {
        "analyze": SkillAction(
            name="analyze",
            description=(
                "Analyze a source file: extract entities, identify "
                "structure, summarize key points. Returns the "
                "analyzer's structured output."
            ),
            handler=_analyze,
            input_schema={
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Path to the source file",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force re-analysis (bypass cache)",
                        "default": False,
                    },
                },
                "required": ["source_path"],
            },
        ),
    }


analyze_skill = AnalyzeSkill()


__all__ = ["AnalyzeSkill", "analyze_skill"]
