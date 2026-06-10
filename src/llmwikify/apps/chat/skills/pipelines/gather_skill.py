"""gather_skill — pipeline: search/extract sources for sub-queries.

Per ``v0.32-execution-plan.md`` Phase 12: this pipeline is
extracted from ``research_skill._act_gather`` (Phase 6) to
become a standalone, independently callable skill.

Pipeline structure
------------------

  1. For each sub-query, call ``wiki.search(query, limit)``
  2. Collect matching pages as source dicts
  3. (Optional) call ``extract_skill`` for full content
     (when ``extract_content=True``)
  4. (Optional, v0.39) When ``enable_web_search=True`` AND
     wiki returned nothing for the sub-query, fall back to
     ``WebSearch`` (DuckDuckGo/Tavily/SearXNG/MiniMax) via
     ``apps/research/web_search.py``.
  5. Return the collected sources

Can be called:

  - **by research_skill** — as the "gather" step in the
    7-step ReAct loop
  - **by the LLM** — as a standalone tool ("gather sources
    for X")
  - **by wiki_query_skill** — as part of the 28-action
    aggregator

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#23)
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


async def _gather(args: dict, ctx: SkillContext) -> SkillResult:
    """Gather sources for a list of sub-queries.

    ``args`` keys:

      - ``sub_queries`` (list[dict]): each dict must have
        a ``"q"`` key with the search query string.
      - ``max_sources_per_query`` (int, default 3): max
        sources to collect per sub-query.
      - ``extract_content`` (bool, default False): if True,
        call ``extract_skill`` on each source URL to get
        full content (slow, use sparingly).

    Returns:

      - ``sources`` (list[dict]): collected source dicts
      - ``_new_sources`` (int): count of new sources added
      - ``_failed_queries`` (list[str]): queries that failed
    """
    sub_queries = args.get("sub_queries", [])
    if not isinstance(sub_queries, list):
        return SkillResult.fail("sub_queries must be a list")

    max_per_query = args.get("max_sources_per_query", 3)
    extract_content = args.get("extract_content", False)
    enable_web_search = bool(args.get("enable_web_search", False))

    wiki = wiki_from_ctx(ctx)
    sources_collected: list[dict] = list(args.get("sources", []))
    existing_urls = {s.get("url", "") for s in sources_collected}
    new_sources = 0
    failed_queries: list[str] = []

    for sq in sub_queries:
        query = sq.get("q", "") if isinstance(sq, dict) else str(sq)
        if not query:
            continue

        if wiki is None:
            # Offline / test mode: produce a synthetic source
            sources_collected.append({
                "url": f"https://offline.example/{query[:30]}",
                "title": f"Synthetic result for: {query[:50]}",
                "source_type": "web",
                "sub_query": query,
                "content_preview": f"Offline content for {query}",
            })
            new_sources += 1
            continue

        # Track sources added for this sub-query to detect wiki-miss
        sources_before = len(sources_collected)

        try:
            r = wiki.search(query, limit=max_per_query)
            for page in (r if isinstance(r, list) else []):
                url = page if isinstance(page, str) else page.get("url", "")
                if url in existing_urls:
                    continue
                source: dict[str, Any] = {
                    "url": url,
                    "title": url if isinstance(page, str) else page.get("title", url),
                    "source_type": "wiki",
                    "sub_query": query,
                }
                sources_collected.append(source)
                existing_urls.add(url)
                new_sources += 1

            # Optionally extract full content
            if extract_content and wiki is not None:
                for s in sources_collected:
                    if s.get("sub_query") == query and not s.get("content"):
                        try:
                            from llmwikify.apps.chat.skills.actions.extract_action import (
                                extract_skill,
                            )
                            er = await extract_skill.actions["extract"].handler(
                                {"url_or_path": s["url"]}, ctx,
                            )
                            if er.status == "ok":
                                s["content"] = er.data.get("content", "")
                        except Exception as e:
                            logger.debug("extract failed for %s: %s", s["url"], e)

            # Fallback to web search when wiki yielded nothing for this query
            # and the caller opted in via enable_web_search=True.
            if (
                enable_web_search
                and len(sources_collected) == sources_before
            ):
                try:
                    from llmwikify.apps.research.web_search import WebSearch
                    searcher = WebSearch(ctx.config or {})
                    web_results = await searcher.search(
                        query, num_results=max_per_query,
                    )
                    for wr in web_results:
                        if not wr.url or wr.url in existing_urls:
                            continue
                        sources_collected.append({
                            "url": wr.url,
                            "title": wr.title or wr.url,
                            "source_type": "web",
                            "sub_query": query,
                            "content_preview": wr.snippet or "",
                        })
                        existing_urls.add(wr.url)
                        new_sources += 1
                except Exception as e:
                    logger.debug(
                        "web_search fallback failed for %s: %s", query, e,
                    )

        except Exception as e:
            logger.warning("gather failed for sub_query %s: %s", query, e)
            failed_queries.append(query)

    return SkillResult.ok({
        "sources": sources_collected,
        "_new_sources": new_sources,
        "_failed_queries": failed_queries,
    })


# ─── Skill declaration ─────────────────────────────────────────


class GatherSkill(Skill):
    """Pipeline: search/extract sources for sub-queries.

    Can be called standalone ("gather sources for X") or
    composed by research_skill as its "gather" step.
    """

    name = "gather"
    description = (
        "Gather multi-source information for a set of sub-queries. "
        "Searches wiki and optionally extracts full content."
    )
    actions = {
        "gather_for_research": SkillAction(
            name="gather_for_research",
            description=(
                "Search for sources matching a list of sub-queries. "
                "Returns collected source dicts with url, title, "
                "source_type, and sub_query fields."
            ),
            handler=_gather,
            input_schema={
                "type": "object",
                "properties": {
                    "sub_queries": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of sub-query dicts with 'q' key",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Existing sources to merge with (optional)",
                    },
                    "max_sources_per_query": {
                        "type": "integer",
                        "description": "Max sources per sub-query (default 3)",
                        "default": 3,
                    },
                    "extract_content": {
                        "type": "boolean",
                        "description": "If True, extract full content from each URL (slow)",
                        "default": False,
                    },
                    "enable_web_search": {
                        "type": "boolean",
                        "description": (
                            "If True, fall back to external web search "
                            "(DuckDuckGo/Tavily/SearXNG/MiniMax) when the "
                            "local wiki returns no results for a sub-query. "
                            "Default False to preserve wiki-first behavior."
                        ),
                        "default": False,
                    },
                },
                "required": ["sub_queries"],
            },
        ),
    }


gather_skill = GatherSkill()


__all__ = ["GatherSkill", "gather_skill"]
