"""web_search_skill — external web search via multi-provider fallback chain.

This is the 24th/25th/26th base action exposed to the LLM via the
Skill framework. It provides LLM-callable access to external web
search, complementing the wiki-local ``SearchSkill`` (which only
queries the user's ingested knowledge base).

Actions
-------

  - ``search_web(query, num_results)`` — general web search.
    Routes through the configured provider chain (SearXNG →
    MiniMax → Tavily → DuckDuckGo, in fallback order).
  - ``search_youtube(query, num_results)`` — YouTube search via
    ``site:youtube.com`` prefix on DuckDuckGo/Tavily/SearXNG.
  - ``search_news(query, num_results)`` — news-oriented search
    via ``site:news.google.com`` prefix. **Note:** uses the same
    provider chain as ``search_web``; a dedicated news provider
    is a future enhancement.

Implementation
--------------

Thin wrapper over ``llmwikify.apps.research.web_search.WebSearch``,
which implements the provider fallback chain. The skill reuses the
research engine's existing search infrastructure rather than
duplicating it.

Configuration
-------------

The provider chain is configured via ``ctx.config`` keys
(matching ``apps/research/web_search.py::create_search_provider``):

  - ``search_provider``: ``"auto"`` | ``"searxng"`` | ``"minimax"``
    | ``"tavily"`` | ``"duckduckgo"``
  - ``searxng_url``: SearXNG base URL
  - ``minimax_api_key``: MiniMax Token Plan API key
  - ``minimax_api_host``: API host (default ``https://api.minimaxi.com``)
  - ``tavily_api_key``: Tavily API key
  - ``web_search_results_per_query``: default 5

This is the 24-26th of the v0.32 base actions per
``v0.32-skill-restructure.md`` §3.1.
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Action handlers ─────────────────────────────────────────────


async def _search_web(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Search the public web via the configured provider chain.

    Args keys:
      - ``query`` (str): search query string.
      - ``num_results`` (int, default 5): max results to return.

    Returns:
      - ``results``: list of ``{"title", "url", "snippet"}`` dicts.
      - ``count``: number of results returned.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return SkillResult.fail("query is required")

    num_results = _validate_num_results(args)
    if isinstance(num_results, SkillResult):
        return num_results

    return await _do_search(query, num_results, ctx, prefix=None)


async def _search_youtube(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Search YouTube via ``site:youtube.com`` routing.

    Args keys:
      - ``query`` (str): search query string.
      - ``num_results`` (int, default 5): max results to return.

    Returns:
      - ``results``: list of YouTube video dicts.
      - ``count``: number of results returned.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return SkillResult.fail("query is required")

    num_results = _validate_num_results(args)
    if isinstance(num_results, SkillResult):
        return num_results

    return await _do_search(
        f"site:youtube.com {query}", num_results, ctx, prefix="youtube",
    )


async def _search_news(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Search news-oriented sources via ``site:news.google.com`` routing.

    **Note:** This uses the same provider chain as ``search_web``;
    a dedicated news provider (e.g. newsapi.org) is a future
    enhancement.

    Args keys:
      - ``query`` (str): search query string.
      - ``num_results`` (int, default 5): max results to return.

    Returns:
      - ``results``: list of news result dicts.
      - ``count``: number of results returned.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return SkillResult.fail("query is required")

    num_results = _validate_num_results(args)
    if isinstance(num_results, SkillResult):
        return num_results

    return await _do_search(
        f"site:news.google.com {query}", num_results, ctx, prefix="news",
    )


def _validate_num_results(args: dict[str, Any]) -> int | SkillResult:
    """Extract and validate ``num_results`` arg.

    Returns the validated int on success, or a SkillResult.fail
    on error. Defaults to 5 when ``num_results`` is missing or
    None (NOT when it's 0 — explicit 0 is rejected).
    """
    raw = args.get("num_results")
    if raw is None:
        return 5
    try:
        num_results = int(raw)
    except (TypeError, ValueError):
        return SkillResult.fail(f"num_results must be an integer, got {raw!r}")
    if num_results < 1 or num_results > 50:
        return SkillResult.fail("num_results must be between 1 and 50")
    return num_results


async def _do_search(
    query: str,
    num_results: int,
    ctx: SkillContext,
    *,
    prefix: str | None,
) -> SkillResult:
    """Shared search implementation across all three actions."""
    # Lazy import: WebSearch lives in apps/research (L3 dependency).
    # Imported here to keep module load cheap when skill isn't used.
    try:
        from llmwikify.apps.research.web_search import WebSearch
    except Exception as e:
        logger.error("Failed to import WebSearch: %s", e)
        return SkillResult.fail(f"WebSearch import failed: {e!r}")

    config = ctx.config or {}
    try:
        searcher = WebSearch(config)
        results = await searcher.search(query, num_results=num_results)
    except Exception as e:
        logger.warning(
            "web_search failed (prefix=%s, query=%r): %s",
            prefix, query[:60], e,
        )
        return SkillResult.fail(f"web_search failed: {e!r}")

    payload = [
        {"title": r.title, "url": r.url, "snippet": r.snippet}
        for r in results
    ]
    return SkillResult.ok({
        "results": payload,
        "count": len(payload),
        "query": query,
        "source_prefix": prefix or "web",
    })


# ─── Skill declaration ──────────────────────────────────────────


class WebSearchSkill(Skill):
    """External web search via DuckDuckGo / Tavily / SearXNG / MiniMax."""

    name = "web_search"
    description = (
        "Search the public web via DuckDuckGo, Tavily, SearXNG, or MiniMax "
        "(configurable fallback chain). Returns titles, URLs, and snippets."
    )
    actions = {
        "search_web": SkillAction(
            name="search_web",
            description=(
                "Search the public web for the given query. Returns up to "
                "num_results results with title, url, and snippet fields. "
                "Use this when the user's question requires current or "
                "external information not present in the local wiki."
            ),
            handler=_search_web,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string (required).",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Max results to return (1-50, default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
        "search_youtube": SkillAction(
            name="search_youtube",
            description=(
                "Search YouTube for videos matching the query. Returns "
                "video result dicts with title, url, and snippet. Use "
                "this when the user asks for video content or tutorials."
            ),
            handler=_search_youtube,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string (required).",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Max results to return (1-50, default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
        "search_news": SkillAction(
            name="search_news",
            description=(
                "Search news sources (site:news.google.com) for recent "
                "articles matching the query. Returns news result dicts "
                "with title, url, and snippet. Use this when the user "
                "asks for current events or recent developments."
            ),
            handler=_search_news,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string (required).",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Max results to return (1-50, default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
    }


web_search_skill = WebSearchSkill()


__all__ = ["WebSearchSkill", "web_search_skill"]