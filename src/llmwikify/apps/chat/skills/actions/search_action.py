"""search_skill — full-text search across wiki pages + web.

Thin wrapper over ``Wiki.search(query, limit)``.

  Action: ``search(query, limit)``
  Returns: ``{"hits": list[str], "total": int}`` (the underlying
           Wiki method's return value is forwarded verbatim)

This is one of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

from typing import Any

from llmwikify.apps.chat.skills.actions._helpers import safe_call, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _search(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    query = args.get("query", "")
    limit = args.get("limit", 10)
    return safe_call(wiki.search, query, limit, error_prefix="search failed")


class SearchSkill(Skill):
    """Action wrapper for full-text wiki/web search."""

    name = "search"
    description = "Full-text search across wiki + web"
    actions = {
        "search": SkillAction(
            name="search",
            description=(
                "Search across wiki pages and the web. Returns a list "
                "of matching pages (wiki) or snippets (web)."
            ),
            handler=_search,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results", "default": 10},
                },
                "required": ["query"],
            },
        ),
    }


search_skill = SearchSkill()


__all__ = ["SearchSkill", "search_skill"]
