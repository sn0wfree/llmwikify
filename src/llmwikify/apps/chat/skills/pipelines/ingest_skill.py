"""ingest_skill — pipeline: extract + write + read orchestration.

Per ``v0.32-execution-plan.md`` Phase 16: this pipeline
orchestrates the full ingest cycle for adding external
content to the wiki.

Pipeline structure
------------------

  1. **Extract** — fetch and parse content from a URL or file
  2. **Write** — write the extracted content to a wiki page
  3. **Read** — read back the written page to verify

Can be called:

  - **by the LLM** — as a standalone tool ("ingest this URL
    into the wiki")
  - **by wiki_query_skill** — as part of the 28-action
    aggregator
  - **by the ingest hook** — automated background ingest

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#24)
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.skills.actions._helpers import wiki_from_ctx
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Action handler ───────────────────────────────────────────────


async def _ingest(args: dict, ctx: SkillContext) -> SkillResult:
    """Ingest external content into the wiki.

    ``args`` keys:

      - ``url_or_path`` (str, required): URL or file path to
        extract content from.
      - ``page_name`` (str, optional): target wiki page name.
        If not provided, derived from the URL/path.
      - ``wiki_id`` (str, optional): target wiki ID. If not
        provided, uses the default wiki.
      - ``skip_extract`` (bool, default False): if True, treat
        ``url_or_path`` as already-extracted content to write.
      - ``content`` (str, optional): raw content to write
        directly (bypasses extraction).

    Returns:

      - ``page_name`` (str): name of the written wiki page
      - ``extracted`` (bool): whether content was extracted
      - ``written`` (bool): whether content was written
      - ``read_back`` (dict): the read-back page data
    """
    url_or_path = args.get("url_or_path", "")
    page_name = args.get("page_name", "")
    skip_extract = args.get("skip_extract", False)
    direct_content = args.get("content", "")

    if not url_or_path and not direct_content:
        return SkillResult.fail("url_or_path or content is required")

    wiki = wiki_from_ctx(ctx)
    extracted_content = ""
    was_extracted = False

    # Step 1: Extract content (unless skipped or direct content provided)
    if direct_content:
        extracted_content = direct_content
        if not page_name:
            page_name = _derive_page_name(url_or_path or "untitled")
    elif not skip_extract and url_or_path:
        try:
            from llmwikify.apps.chat.skills.actions.extract_action import (
                extract_skill,
            )
            er = await extract_skill.actions["extract"].handler(
                {"url_or_path": url_or_path}, ctx,
            )
            if er.status == "ok":
                extracted_content = er.data.get("content", "")
                was_extracted = True
                if not page_name:
                    page_name = er.data.get("page_name", "") or _derive_page_name(url_or_path)
            else:
                return SkillResult.fail(f"Extract failed: {er.error}")
        except Exception as e:
            return SkillResult.fail(f"Extract error: {e}")
    else:
        # skip_extract=True, no direct content — read from path
        if url_or_path:
            from pathlib import Path
            p = Path(url_or_path)
            if p.exists():
                extracted_content = p.read_text(encoding="utf-8")
                was_extracted = True
                if not page_name:
                    page_name = _derive_page_name(url_or_path)
            else:
                return SkillResult.fail(f"File not found: {url_or_path}")

    if not extracted_content:
        return SkillResult.fail("No content to write")

    if not page_name:
        page_name = "untitled"

    # Step 2: Write to wiki
    was_written = False
    if wiki is not None:
        try:
            from llmwikify.apps.chat.skills.actions.write_action import (
                write_skill,
            )
            wr = await write_skill.actions["write_page"].handler(
                {"page_name": page_name, "content": extracted_content}, ctx,
            )
            if wr.status == "ok":
                was_written = True
            else:
                logger.warning("Write failed for %s: %s", page_name, wr.error)
        except Exception as e:
            logger.warning("Write error for %s: %s", page_name, e)

    # Step 3: Read back to verify
    read_back = {}
    if wiki is not None and was_written:
        try:
            from llmwikify.apps.chat.skills.actions.read_action import (
                read_skill,
            )
            rr = await read_skill.actions["read_page"].handler(
                {"page_name": page_name}, ctx,
            )
            if rr.status == "ok":
                read_back = rr.data
        except Exception as e:
            logger.debug("Read-back failed for %s: %s", page_name, e)

    return SkillResult.ok({
        "page_name": page_name,
        "extracted": was_extracted,
        "written": was_written,
        "read_back": read_back,
    })


def _derive_page_name(url_or_path: str) -> str:
    """Derive a wiki page name from a URL or file path."""
    from pathlib import Path
    p = Path(url_or_path)
    name = p.stem if p.suffix else p.name
    # Clean up for wiki page naming
    name = name.replace("-", "_").replace(" ", "_")
    return name[:100] if name else "untitled"


# ─── Skill declaration ─────────────────────────────────────────


class IngestSkill(Skill):
    """Pipeline: extract + write + read orchestration.

    Orchestrates the full ingest cycle for adding external
    content to the wiki.
    """

    name = "ingest"
    description = (
        "Ingest external content into the wiki. Extracts from "
        "URL/file, writes to wiki page, and reads back to verify."
    )
    actions = {
        "ingest_content": SkillAction(
            name="ingest_content",
            description=(
                "Extract content from a URL or file, write it to "
                "a wiki page, and read back to verify. Returns "
                "the page name and verification status."
            ),
            handler=_ingest,
            input_schema={
                "type": "object",
                "properties": {
                    "url_or_path": {
                        "type": "string",
                        "description": "URL or file path to extract content from",
                    },
                    "page_name": {
                        "type": "string",
                        "description": "Target wiki page name (derived from URL if not provided)",
                    },
                    "wiki_id": {
                        "type": "string",
                        "description": "Target wiki ID (uses default if not provided)",
                    },
                    "skip_extract": {
                        "type": "boolean",
                        "description": "If True, read content directly from file path",
                        "default": False,
                    },
                    "content": {
                        "type": "string",
                        "description": "Raw content to write directly (bypasses extraction)",
                    },
                },
            },
        ),
    }


ingest_skill = IngestSkill()


__all__ = ["IngestSkill", "ingest_skill"]
