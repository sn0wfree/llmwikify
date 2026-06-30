"""Web search with multiple provider support.

Providers (in fallback order):
1. SearXNG — self-hosted meta search engine (free, no API key)
2. MiniMax — Token Plan web search API (450 req/day)
3. Tavily — AI-optimized search API (free tier: 1000/month)
4. DuckDuckGo — free, may fail in restricted networks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


# ---------------------------------------------------------------------------
# Provider Protocol
# ---------------------------------------------------------------------------

class SearchProvider(Protocol):
    async def search(self, query: str, num_results: int) -> list[SearchResult]: ...


# ---------------------------------------------------------------------------
# SearXNG Provider
# ---------------------------------------------------------------------------

class SearXNGProvider:
    """SearXNG self-hosted meta search engine."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, num_results: int) -> list[SearchResult]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json", "pageno": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                )
                for r in data.get("results", [])[:num_results]
                if r.get("url")
            ]


# ---------------------------------------------------------------------------
# Tavily Provider
# ---------------------------------------------------------------------------

class TavilyProvider:
    """Tavily AI-optimized search API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, num_results: int) -> list[SearchResult]:
        import asyncio

        from tavily import TavilyClient

        client = TavilyClient(api_key=self.api_key)

        def _search():
            return client.search(query, max_results=num_results, include_raw_content=False)

        response = await asyncio.to_thread(_search)
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in response.get("results", [])
            if r.get("url")
        ]


# ---------------------------------------------------------------------------
# DuckDuckGo Provider
# ---------------------------------------------------------------------------

class DuckDuckGoProvider:
    """DuckDuckGo search (free, may fail in restricted networks)."""

    async def search(self, query: str, num_results: int) -> list[SearchResult]:
        import asyncio

        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        def _search():
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=num_results)
                return list(results) if results else []

        results = await asyncio.to_thread(_search)
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            )
            for r in results
        ]


# ---------------------------------------------------------------------------
# MiniMax Provider
# ---------------------------------------------------------------------------

class MiniMaxSearchProvider:
    """MiniMax Token Plan web search API (450 req/day).

    Uses the coding_plan search endpoint:
        POST {api_host}/v1/coding_plan/search
    """

    def __init__(self, api_key: str, api_host: str = "https://api.minimaxi.com"):
        self.api_key = api_key
        self.api_host = api_host.rstrip("/")

    async def search(self, query: str, num_results: int) -> list[SearchResult]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.api_host}/v1/coding_plan/search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "MM-API-Source": "Minimax-MCP",
                },
                json={"q": query},
            )
            resp.raise_for_status()
            data = resp.json()

        # Check API-level error
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax API error {base_resp.get('status_code')}: "
                f"{base_resp.get('status_msg', 'unknown')}"
            )

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
            )
            for r in data.get("organic", [])[:num_results]
            if r.get("link")
        ]


# ---------------------------------------------------------------------------
# Fallback Chain
# ---------------------------------------------------------------------------

class FallbackSearchProvider:
    """Tries providers in order, returns first successful results."""

    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers

    async def search(self, query: str, num_results: int) -> list[SearchResult]:
        for provider in self.providers:
            name = type(provider).__name__
            try:
                results = await provider.search(query, num_results)
                if results:
                    logger.info("Search via %s returned %d results", name, len(results))
                    return results
                logger.warning("Search via %s returned 0 results, trying next", name)
            except Exception as e:
                logger.warning("Search provider %s failed: %s", name, e)
        logger.error("All search providers failed for: %s", query)
        return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_search_provider(config: dict[str, Any]) -> FallbackSearchProvider:
    """Create search provider chain based on config.

    Config keys:
        search_provider: "auto" | "searxng" | "minimax" | "tavily" | "duckduckgo"
        searxng_url: SearXNG base URL (e.g. "http://localhost:8888")
        minimax_api_key: MiniMax Token Plan API key
        minimax_api_host: MiniMax API host (default: "https://api.minimaxi.com")
        tavily_api_key: Tavily API key (e.g. "tvly-xxxxx")
    """
    provider_name = config.get("search_provider", "auto")
    chain: list[SearchProvider] = []

    if provider_name in ("auto", "searxng"):
        searxng_url = config.get("searxng_url")
        if searxng_url:
            chain.append(SearXNGProvider(searxng_url))
            logger.info("Registered SearXNG provider: %s", searxng_url)

    if provider_name in ("auto", "minimax"):
        minimax_key = config.get("minimax_api_key")
        if minimax_key:
            minimax_host = config.get("minimax_api_host", "https://api.minimaxi.com")
            chain.append(MiniMaxSearchProvider(minimax_key, minimax_host))
            logger.info("Registered MiniMax provider")

    if provider_name in ("auto", "tavily"):
        tavily_key = config.get("tavily_api_key")
        if tavily_key:
            chain.append(TavilyProvider(tavily_key))
            logger.info("Registered Tavily provider")

    if provider_name in ("auto", "duckduckgo"):
        chain.append(DuckDuckGoProvider())
        logger.info("Registered DuckDuckGo provider")

    if not chain:
        chain.append(DuckDuckGoProvider())
        logger.warning("No search providers configured, falling back to DuckDuckGo")

    return FallbackSearchProvider(chain)


# ---------------------------------------------------------------------------
# WebSearch (backward-compatible wrapper)
# ---------------------------------------------------------------------------

class WebSearch:
    """Web search wrapper — delegates to configured provider chain."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._provider: FallbackSearchProvider | None = None

    def _get_provider(self) -> FallbackSearchProvider:
        if self._provider is None:
            self._provider = create_search_provider(self.config)
        return self._provider

    async def search(self, query: str, num_results: int | None = None) -> list[SearchResult]:
        """Execute search using configured provider chain."""
        num = num_results or self.config.get("web_search_results_per_query", 5)
        return await self._get_provider().search(query, num)

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
