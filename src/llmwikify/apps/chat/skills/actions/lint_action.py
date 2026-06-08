"""lint_skill — wiki health check (orchestrates 8 detect_action).

Thin wrapper over ``Wiki.lint(mode, limit, force,
generate_investigations)``.

  Action: ``lint(mode, limit, force, generate_investigations)``
  Returns: ``dict`` (the underlying Wiki method's return value)

This is a meta-action: the actual detection work is done
by 8 ``detect_*_skill`` actions (Phase 5 deliverables),
each of which is itself a thin wrapper over
``Wiki._detect_*()``. The lint action aggregates their
results.

Per the design (§3.1), this is the 5th of the 14 base
actions.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions._helpers import safe_call, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _lint(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    return safe_call(
        wiki.lint,
        mode=args.get("mode", "check"),
        limit=args.get("limit", 10),
        force=args.get("force", False),
        generate_investigations=args.get("generate_investigations", False),
        error_prefix="lint failed",
    )


class LintSkill(Skill):
    """Action wrapper for wiki health check (orchestrates 8 detect actions)."""

    name = "lint"
    description = "Wiki health check + lint detection (orchestrates 8 detect_action)"
    actions = {
        "lint": SkillAction(
            name="lint",
            description=(
                "Run the wiki's lint pipeline. Aggregates results from "
                "the 8 detect actions (knowledge_gaps, data_gaps, "
                "outdated_pages, dated_claims, query_page_overlap, "
                "missing_cross_refs, potential_contradictions, "
                "redundancy). Optionally generates investigation "
                "questions for the largest gaps."
            ),
            handler=_lint,
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["check", "fix"],
                        "description": "Lint mode",
                        "default": "check",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max issues to return per detect",
                        "default": 10,
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force re-lint (bypass cache)",
                        "default": False,
                    },
                    "generate_investigations": {
                        "type": "boolean",
                        "description": "Generate investigation questions for gaps",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
    }


lint_skill = LintSkill()


__all__ = ["LintSkill", "lint_skill"]
