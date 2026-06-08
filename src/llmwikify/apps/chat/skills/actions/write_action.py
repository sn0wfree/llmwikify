"""write_skill — write a wiki page (requires pre-execution confirmation).

Thin wrapper over ``Wiki.write_page(page_name, content)``.

  Action: ``write(page_name, content)``
  Returns: ``{"written": True, "page_name": str}``

This is a WRITE action — it requires pre-execution
confirmation (``requires_confirmation="pre"``). The
framework's ConfirmationRequiredError path is documented in
``apps/chat/skills/errors.py``.

One of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions._helpers import safe_call, wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _write(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = wiki_from_ctx(ctx)
    if wiki is None:
        return SkillResult.fail("No wiki in context")
    page_name = args.get("page_name", "")
    content = args.get("content", "")
    return safe_call(
        wiki.write_page, page_name, content,
        error_prefix="write failed",
    )


class WriteSkill(Skill):
    """Action wrapper for writing a wiki page (confirmation required)."""

    name = "write"
    description = "Write a wiki page (requires user confirmation)"
    actions = {
        "write": SkillAction(
            name="write",
            description=(
                "Write markdown content to a wiki page. "
                "REQUIRES user confirmation before execution."
            ),
            handler=_write,
            requires_confirmation="pre",
            action_type="write",
            input_schema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Page path (e.g. entities/PersonName)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown content to write",
                    },
                },
                "required": ["page_name", "content"],
            },
        ),
    }


write_skill = WriteSkill()


__all__ = ["WriteSkill", "write_skill"]
