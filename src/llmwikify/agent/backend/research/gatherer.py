"""Parallel source gathering with semaphore-controlled concurrency."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ....extractors.base import ExtractedContent
from ....extractors.web import extract_url
from ....extractors.youtube import extract_youtube
from ..db import AgentDatabase
from .session import ResearchSessionManager

logger = logging.getLogger(__name__)


class SourceGatherer:
    """Gathers content from multiple sources in parallel."""

    def __init__(
        self,
        wiki: Any,
        db: AgentDatabase,
        session_manager: ResearchSessionManager,
        config: dict[str, Any],
    ):
        self.wiki = wiki
        self.db = db
        self.session_manager = session_manager
        self.config = config
        self._max_content = config.get("max_source_content_length", 500000)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for dedup comparison."""
        url = url.rstrip("/").lower()
        # Remove common prefixes for consistency
        for prefix in ("http://", "https://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url

    async def gather(self, sub_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Gather content for all sub-queries with controlled parallelism.

        Returns list of SSE events to yield. Deduplicates URLs across sub-queries.
        """
        max_parallel = self.config.get("max_parallel_gathering", 5)
        # Hard timeout per sub-query task: 90s
        per_query_timeout = 90
        # Total timeout for entire gathering: 10 minutes
        total_timeout = 600
        semaphore = asyncio.Semaphore(max_parallel)
        events: list[dict[str, Any]] = []

        # Build set of already-seen URLs from existing sources (for resume)
        session_id = self.session_manager.session_id
        existing_sources = self.db.get_sources(session_id) if session_id else []
        seen_urls: set[str] = set()
        for s in existing_sources:
            url = s.get("url", "")
            if url:
                seen_urls.add(self._normalize_url(url))

        async def process_one(sq: dict[str, Any]) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._gather_one(sq, seen_urls),
                        timeout=per_query_timeout,
                    )
                except asyncio.TimeoutError:
                    sq_id = sq.get("id", "?")
                    logger.warning("Sub-query %s timed out after %ds", sq_id, per_query_timeout)
                    self.session_manager.fail_sub_query(sq_id, f"Gathering timed out after {per_query_timeout}s")
                    return [{"type": "sub_query_failed", "sub_query_id": sq_id, "error": f"Gathering timed out after {per_query_timeout}s"}]

        tasks = [process_one(sq) for sq in sub_queries]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=total_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Entire gathering stage timed out after %ds", total_timeout)
            # Cancel remaining tasks
            for t in tasks:
                if not t.done():
                    t.cancel()
            # Return what we have so far
            sources = self.db.get_sources(session_id) if session_id else []
            events.append({"type": "progress", "progress": 0.4, "message": f"Gathering timed out, {len(sources)} sources collected"})
            return events

        for r in results:
            if isinstance(r, Exception):
                events.append({"type": "sub_query_failed", "error": str(r)})
            elif isinstance(r, list):
                events.extend(r)

        return events

    async def _gather_one(self, sub_query: dict[str, Any], seen_urls: set[str]) -> list[dict[str, Any]]:
        """Gather content for a single sub-query. Returns list of SSE events.

        Skips URLs already in seen_urls for deduplication.
        """
        sq_id = sub_query["id"]
        source_type = sub_query["source_type"]
        url = sub_query.get("url", "")
        query = sub_query["query"]
        session_id = self.session_manager.session_id
        events: list[dict[str, Any]] = []
        num_results = self.config.get("web_search_results_per_query", 5)

        try:
            urls_to_fetch: list[str] = []

            # For web/youtube without URL, search first
            if source_type in ("web", "youtube") and not url:
                from .web_search import WebSearch
                searcher = WebSearch(self.config)
                try:
                    if source_type == "youtube":
                        search_results = await asyncio.wait_for(
                            searcher.search(f"site:youtube.com {query}", num_results=num_results),
                            timeout=30,
                        )
                    else:
                        search_results = await asyncio.wait_for(
                            searcher.search(query, num_results=num_results),
                            timeout=30,
                        )
                except asyncio.TimeoutError:
                    raise ValueError(f"Search timed out for: {query}")
                # Filter out already-seen URLs
                for r in search_results:
                    if r.url and self._normalize_url(r.url) not in seen_urls:
                        urls_to_fetch.append(r.url)
                if not urls_to_fetch:
                    raise ValueError(f"No new search results for: {query}")
            elif url:
                if self._normalize_url(url) in seen_urls:
                    raise ValueError(f"URL already gathered: {url}")
                urls_to_fetch = [url]

            if source_type == "wiki":
                pages = self.wiki.search(query, limit=min(num_results, 5))
                for page in pages[:num_results]:
                    try:
                        page_name = page.get("name", query)
                        wiki_url = f"wiki://{page_name}"
                        if self._normalize_url(wiki_url) in seen_urls:
                            continue
                        page_content = self.wiki.page_io.read_page(page_name)
                        content = str(page_content) if page_content else ""
                        if not content:
                            continue
                        content = content[: self._max_content]
                        seen_urls.add(self._normalize_url(wiki_url))
                        source_id = self.session_manager.add_source(
                            session_id=session_id,
                            sub_query_id=sq_id,
                            source_type=source_type,
                            url=wiki_url,
                            title=page_name,
                            content_length=len(content),
                            content_preview=content[:500],
                            content=content,
                        )
                        events.append({
                            "type": "source_gathered",
                            "source_id": source_id,
                            "source_type": source_type,
                            "title": page_name,
                            "url": wiki_url,
                        })
                    except Exception as e:
                        logger.warning("Wiki page read failed for %s: %s", page.get("name"), e)
                if events:
                    self.session_manager.complete_sub_query(sq_id, {"sources_count": len(events)})
                else:
                    raise ValueError(f"No wiki pages found for: {query}")
            else:
                # Fetch each URL (already deduped above)
                for fetch_url in urls_to_fetch:
                    try:
                        content = await self._fetch_url(source_type, fetch_url)
                        if not content:
                            continue
                        content = content[: self._max_content]
                        seen_urls.add(self._normalize_url(fetch_url))
                        source_id = self.session_manager.add_source(
                            session_id=session_id,
                            sub_query_id=sq_id,
                            source_type=source_type,
                            url=fetch_url,
                            title=fetch_url,
                            content_length=len(content),
                            content_preview=content[:500],
                            content=content,
                        )
                        events.append({
                            "type": "source_gathered",
                            "source_id": source_id,
                            "source_type": source_type,
                            "title": fetch_url,
                            "url": fetch_url,
                        })
                    except Exception as e:
                        logger.warning("Fetch failed for %s: %s", fetch_url, e)

                if events:
                    self.session_manager.complete_sub_query(sq_id, {"sources_count": len(events)})
                else:
                    raise ValueError(f"All fetches failed for: {query}")

        except Exception as e:
            logger.warning("Gather failed for sub_query %s (%s): %s", sq_id, source_type, e)
            self.session_manager.fail_sub_query(sq_id, str(e))
            events.append({
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": str(e),
            })

        return events

    async def _fetch_url(self, source_type: str, url: str) -> str:
        """Fetch content from a URL based on source type, with retry and hard timeout."""
        from .retry import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)
        call_timeout = self.config.get("llm_call_timeout_seconds", 120)
        # Hard timeout per URL: max 60s (prevents indefinite blocking in gathering)
        hard_timeout = 60

        async def _do_fetch() -> str:
            if source_type == "youtube":
                result = extract_youtube(url)
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "YouTube extraction failed"))
                return result.text
            elif source_type == "pdf":
                from pathlib import Path
                from ....extractors.pdf import extract_pdf
                result = extract_pdf(Path(url))
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "PDF extraction failed"))
                return result.text
            elif source_type == "web":
                result = extract_url(url)
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "Web extraction failed"))
                return result.text
            else:
                raise ValueError(f"Unsupported source_type: {source_type}")

        try:
            return await asyncio.wait_for(
                retry_async(_do_fetch, max_attempts=max_attempts, base_delay=2.0,
                           call_timeout=min(call_timeout, hard_timeout),
                           exceptions=(ValueError, ConnectionError, TimeoutError)),
                timeout=hard_timeout,
            )
        except asyncio.TimeoutError:
            raise ValueError(f"Fetch timed out after {hard_timeout}s: {url}")
