"""Web search using DuckDuckGo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


class WebSearch:
    """DuckDuckGo web search wrapper."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def search(self, query: str, num_results: int | None = None) -> list[SearchResult]:
        """Execute a DuckDuckGo search."""
        num = num_results or self.config.get("web_search_results_per_query", 5)
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num))
            return [
                SearchResult(title=r.get("title", ""), url=r.get("href", ""), snippet=r.get("body", ""))
                for r in results
            ]
        except Exception as e:
            logger.warning("DuckDuckGo search failed for '%s': %s", query, e)
            return []

    async def search_with_type(self, query: str, source_type: str) -> list[dict[str, Any]]:
        """Search with specific source type routing."""
        if source_type == "web":
            results = await self.search(query)
            return [{"query": query, "source_type": "web", "url": r.url, "title": r.title} for r in results]
        elif source_type == "youtube":
            results = await self.search(f"site:youtube.com {query}")
            return [{"query": query, "source_type": "youtube", "url": r.url, "title": r.title} for r in results]
        elif source_type == "wiki":
            return [{"query": query, "source_type": "wiki", "url": "", "title": query}]
        return []
