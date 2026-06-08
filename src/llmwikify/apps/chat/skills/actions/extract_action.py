"""extract_skill — extract content from a file/URL/YouTube.

Thin wrapper over the L1 ``foundation.extractors`` layer.

  Action: ``extract(url_or_path)``
  Returns: ``{"content": str, "metadata": dict}``

This is one of the 14 base actions per
``v0.32-skill-restructure.md`` §3.1. The actual extraction
logic lives in ``llmwikify.foundation.extractors`` and is
called via a simple dispatch (URL vs file path vs YouTube).
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions._helpers import safe_call
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)


async def _extract(args: dict, ctx: SkillContext) -> SkillResult:
    """Extract content from a file/URL/YouTube.

    Dispatches to the appropriate L1 extractor:
      - YouTube URL → foundation.extractors.youtube
      - HTTP(S) URL → foundation.extractors.web
      - Local file path → foundation.extractors.file
    """
    url_or_path = args.get("url_or_path", "")
    if not url_or_path:
        return SkillResult.fail("url_or_path is required")

    # YouTube
    if "youtube.com" in url_or_path or "youtu.be" in url_or_path:
        from llmwikify.foundation.extractors.youtube import extract_youtube
        return safe_call(extract_youtube, url_or_path, error_prefix="youtube extract failed")

    # HTTP(S) URL
    if url_or_path.startswith(("http://", "https://")):
        from llmwikify.foundation.extractors.web import extract_web
        return safe_call(extract_web, url_or_path, error_prefix="web extract failed")

    # Local file
    from llmwikify.foundation.extractors.file import extract_file
    return safe_call(extract_file, url_or_path, error_prefix="file extract failed")


class ExtractSkill(Skill):
    """Action wrapper for file/URL/YouTube content extraction."""

    name = "extract"
    description = "Extract content from a file/URL/YouTube"
    actions = {
        "extract": SkillAction(
            name="extract",
            description=(
                "Extract text content from a file path, HTTP(S) URL, "
                "or YouTube URL. Dispatches to the appropriate L1 "
                "extractor based on the input type."
            ),
            handler=_extract,
            input_schema={
                "type": "object",
                "properties": {
                    "url_or_path": {
                        "type": "string",
                        "description": (
                            "File path, HTTP(S) URL, or YouTube URL to extract from"
                        ),
                    },
                },
                "required": ["url_or_path"],
            },
        ),
    }


extract_skill = ExtractSkill()


__all__ = ["ExtractSkill", "extract_skill"]
