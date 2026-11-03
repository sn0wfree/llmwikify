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

import asyncio
import logging

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)

#: Hard ceiling for one extraction (network fetch + parsing).
EXTRACT_TIMEOUT_SECONDS = 60.0


async def _extract(args: dict, ctx: SkillContext) -> SkillResult:
    """Extract content from a file/URL/YouTube.

    Dispatches through ``foundation.extractors.base.extract()``, the single
    entry point that auto-detects the source type (YouTube / HTTP URL /
    local file) and picks the right extractor. Relative file paths are
    resolved against the wiki root, matching ``wiki.ingest_source()``.

    Extraction is synchronous and may block for tens of seconds on a slow
    network, so it runs in a worker thread with a hard timeout — calling
    it directly would stall the whole event loop (SSE streams, other
    tools) for the duration.
    """
    url_or_path = args.get("url_or_path", "")
    if not url_or_path:
        return SkillResult.fail("url_or_path is required")

    from llmwikify.foundation.extractors.base import extract

    wiki_root = getattr(getattr(ctx, "wiki", None), "root", None)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(extract, url_or_path, wiki_root=wiki_root),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("extract timed out after %ss: %s", EXTRACT_TIMEOUT_SECONDS, url_or_path)
        return SkillResult.fail(
            f"extract timed out after {EXTRACT_TIMEOUT_SECONDS}s: {url_or_path}"
        )
    except Exception as e:
        logger.warning("extract failed: %s", e, exc_info=True)
        return SkillResult.fail(f"extract failed: {e!r}")

    if result.source_type == "error":
        return SkillResult.fail(
            str(result.metadata.get("error", "extract failed")),
        )

    return SkillResult.ok(
        {
            "content": result.text,
            "title": result.title,
            "source_type": result.source_type,
            "metadata": result.metadata,
        }
    )


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
