"""read_skill — read a wiki page.

Thin wrapper over ``Wiki.read_page(page_name)``.

  Action: ``read(page_name)``
  Returns: ``{"content": str, "page_name": str}``

One of the 14 base actions per
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


async def _read(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    page_name = args.get("page_name", "")
    return safe_call(wiki.read_page, page_name, error_prefix="read failed")


class ReadSkill(Skill):
    """Action wrapper for reading a wiki page."""

    name = "read"
    description = "Read a wiki page (returns markdown content)"
    actions = {
        "read": SkillAction(
            name="read",
            description="Read a wiki page by its name/path. Returns the page's markdown content.",
            handler=_read,
            input_schema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Name or path of the page (e.g. 'entities/PersonName')",
                    },
                },
                "required": ["page_name"],
            },
        ),
    }


read_skill = ReadSkill()


__all__ = ["ReadSkill", "read_skill"]
