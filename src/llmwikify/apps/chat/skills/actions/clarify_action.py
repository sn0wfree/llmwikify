"""clarify_skill — clarify a research query before planning.

  Action: ``clarify(query, wiki_context)``
  Returns: ``{"context": str, "boundaries": str, "position": str,
            "premises": list[str], "scope_check": bool}``

This is the 23rd action (the 3rd discovery per
``v0.32-skill-restructure.md`` §3.1 footer).

The Phase 5 implementation is a **minimal rule-based
fallback** that returns a structured clarification. The
existing ``apps/chat/clarifier.py::ResearchClarifier.clarify``
provides the full LLM-driven version; Phase 6 will wire
this action to it (for now we provide a working stub so
the framework has a callable clarify action).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


def _clarify_fallback(query: str, wiki_context: str = "") -> dict:
    """Rule-based clarification fallback.

    Returns a minimal dict that the research loop can use
    as a seed for further planning. The LLM-driven version
    (``ResearchClarifier.clarify``) produces richer output.
    """
    return {
        "context": f"Research scope for: {query[:120]}",
        "boundaries": "Default boundaries: focused on wiki + recent web sources.",
        "position": "Neutral third-party research perspective.",
        "premises": [
            "User wants a factual, sourced answer.",
            "Sources should be no older than 5 years unless explicitly noted.",
        ],
        "scope_check": True,
        "_source": "rule_based_fallback",
    }


async def _clarify(args: dict, ctx: SkillContext) -> SkillResult:
    """Clarify a research query.

    Phase 5: rule-based fallback. Phase 6 will try the LLM-
    driven ``ResearchClarifier.clarify`` first, falling back
    to this stub on failure (matches the pattern in
    ``apps/chat/clarifier.py``).
    """
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    wiki_context = args.get("wiki_context", "")
    return SkillResult.ok(_clarify_fallback(query=query, wiki_context=wiki_context))


class ClarifySkill(Skill):
    """Action wrapper for query clarification."""

    name = "clarify"
    description = "Clarify a research query before planning"
    actions = {
        "clarify": SkillAction(
            name="clarify",
            description=(
                "Take a research query and produce a structured "
                "clarification: context, boundaries, position, "
                "premises, scope_check. Used at the start of "
                "research_skill to focus the subsequent ReAct loop."
            ),
            handler=_clarify,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research query to clarify"},
                    "wiki_context": {
                        "type": "string",
                        "description": "Optional wiki context (recent edits, gaps)",
                        "default": "",
                    },
                },
                "required": ["query"],
            },
        ),
    }


clarify_skill = ClarifySkill()


__all__ = ["ClarifySkill", "clarify_skill", "_clarify_fallback"]
