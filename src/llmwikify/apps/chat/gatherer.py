"""Parallel source gathering with semaphore-controlled concurrency."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llmwikify.apps.chat.db import AutoResearchDatabase
from llmwikify.apps.chat.harness.source_filter import SourceFilter
from llmwikify.apps.chat.session import ResearchSessionManager
from llmwikify.foundation.extractors.base import ExtractedContent
from llmwikify.foundation.extractors.web import extract_url
from llmwikify.foundation.extractors.youtube import extract_youtube

logger = logging.getLogger(__name__)


class SourceGatherer:
    """Gathers content from multiple sources in parallel."""

    def __init__(
        self,
        wiki: Any,
        db: AutoResearchDatabase,
        session_manager: ResearchSessionManager,
        config: dict[str, Any],
    ):
        self.wiki = wiki
        self.db = db
        self.session_manager = session_manager
        self.config = config
        self._max_content = config.get("max_source_content_length", 500000)
        self._source_filter = SourceFilter(config)

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
        """Gather content for all sub-queries with early-exit optimization.

        Returns list of SSE events to yield. Deduplicates URLs across sub-queries.
        Early exits when 50%+ sub-queries complete, cancelling remaining tasks.
        """
        max_parallel = self.config.get("max_parallel_gathering", 8)
        per_query_timeout = 45
        # Early-exit: continue when this fraction of tasks done
        early_exit_threshold = 0.7
        # Grace period after threshold: wait this long for stragglers
        early_exit_grace = 15
        semaphore = asyncio.Semaphore(max_parallel)
        events: list[dict[str, Any]] = []

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

        tasks = {asyncio.create_task(process_one(sq)): sq for sq in sub_queries}
        total = len(tasks)
        done_count = 0
        threshold_reached = False
        grace_deadline = None

        try:
            while tasks:
                done, pending = await asyncio.wait(
                    tasks.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=per_query_timeout + 5,
                )

                if not done:
                    logger.warning("No tasks completed within timeout, cancelling %d remaining", len(pending))
                    for t in pending:
                        if not t.done():
                            t.exception()  # retrieve to suppress "never retrieved" warning
                            t.cancel()
                    break

                for t in done:
                    sq = tasks.pop(t)
                    try:
                        result = t.result()
                        if isinstance(result, list):
                            events.extend(result)
                        done_count += 1
                    except Exception as e:
                        events.append({"type": "sub_query_failed", "sub_query_id": sq.get("id", "?"), "error": str(e)})
                        done_count += 1

                progress_frac = done_count / total
                if not threshold_reached and progress_frac >= early_exit_threshold:
                    threshold_reached = True
                    grace_deadline = asyncio.get_event_loop().time() + early_exit_grace
                    logger.info(
                        "Gathering threshold reached: %d/%d done (%.0f%%), grace %ds",
                        done_count, total, progress_frac * 100, early_exit_grace,
                    )

                if threshold_reached and pending:
                    if asyncio.get_event_loop().time() >= grace_deadline:
                        logger.info("Grace expired, cancelling %d remaining tasks", len(pending))
                        for t in pending:
                            if not t.done():
                                t.exception()  # retrieve to suppress "never retrieved" warning
                                t.cancel()
                        break

        except asyncio.CancelledError:
            logger.warning("Gathering stage cancelled")

        # Collect any remaining results briefly
        remaining = [t for t in tasks if not t.done()]
        if remaining:
            done, _ = await asyncio.wait(remaining, timeout=5)
            for t in done:
                try:
                    result = t.result()
                    if isinstance(result, list):
                        events.extend(result)
                except Exception:
                    pass

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
                from llmwikify.apps.research.web_search import WebSearch
                searcher = WebSearch(self.config)
                try:
                    if source_type == "youtube":
                        search_results = await asyncio.wait_for(
                            searcher.search(f"site:youtube.com {query}", num_results=num_results),
                            timeout=15,
                        )
                    else:
                        search_results = await asyncio.wait_for(
                            searcher.search(query, num_results=num_results),
                            timeout=15,
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
                        page_content = self.wiki.read_page(page_name)
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
            elif source_type == "web" and not url and self.config.get("parallel_wiki_search", True):
                # Parallel: fetch web results AND search local wiki simultaneously
                web_tasks = [self._fetch_url(source_type, u) for u in urls_to_fetch]
                wiki_pages = []
                try:
                    wiki_pages = self.wiki.search(query, limit=min(3, num_results))
                except Exception as e:
                    logger.debug("Parallel wiki search failed: %s", e)

                # Fetch web content in parallel
                if web_tasks:
                    web_contents = await asyncio.gather(*web_tasks, return_exceptions=True)
                    for fetch_url, content in zip(urls_to_fetch, web_contents):
                        if isinstance(content, Exception):
                            logger.warning("Fetch failed for %s: %s", fetch_url, content)
                            continue
                        if not content:
                            continue
                        content = str(content)[: self._max_content]
                        if self._normalize_url(fetch_url) in seen_urls:
                            continue
                        seen_urls.add(self._normalize_url(fetch_url))
                        # Apply source filter
                        source_candidate = {
                            "url": fetch_url,
                            "content": content,
                            "source_type": source_type,
                            "title": fetch_url,
                        }
                        kept, _ = self._source_filter.filter_sources([source_candidate], query)
                        if not kept:
                            logger.debug("Source filtered out: %s", fetch_url)
                            continue
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

                # Also gather local wiki results
                for page in wiki_pages[:3]:
                    try:
                        page_name = page.get("page_name", query)
                        wiki_url = f"wiki://{page_name}"
                        if self._normalize_url(wiki_url) in seen_urls:
                            continue
                        page_content = self.wiki.read_page(page_name)
                        content = str(page_content) if page_content else ""
                        if not content:
                            continue
                        content = content[: self._max_content]
                        seen_urls.add(self._normalize_url(wiki_url))
                        source_id = self.session_manager.add_source(
                            session_id=session_id,
                            sub_query_id=sq_id,
                            source_type="wiki",
                            url=wiki_url,
                            title=page_name,
                            content_length=len(content),
                            content_preview=content[:500],
                            content=content,
                        )
                        events.append({
                            "type": "source_gathered",
                            "source_id": source_id,
                            "source_type": "wiki",
                            "title": page_name,
                            "url": wiki_url,
                        })
                    except Exception as e:
                        logger.warning("Parallel wiki page read failed for %s: %s", page.get("page_name"), e)

                if events:
                    self.session_manager.complete_sub_query(sq_id, {"sources_count": len(events)})
                else:
                    raise ValueError(f"No results found for: {query}")
            else:
                # Fetch each URL (already deduped above)
                for fetch_url in urls_to_fetch:
                    try:
                        content = await self._fetch_url(source_type, fetch_url)
                        if not content:
                            continue
                        content = content[: self._max_content]
                        seen_urls.add(self._normalize_url(fetch_url))
                        # Apply source filter
                        source_candidate = {
                            "url": fetch_url,
                            "content": content,
                            "source_type": source_type,
                            "title": fetch_url,
                        }
                        kept, _ = self._source_filter.filter_sources([source_candidate], query)
                        if not kept:
                            logger.debug("Source filtered out: %s", fetch_url)
                            continue
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
        """Fetch content from a URL based on source type, with retry and hard timeout.

        Uses asyncio.to_thread for all blocking I/O so that asyncio.wait_for
        can actually cancel on timeout (sync calls in a coroutine cannot be
        cancelled otherwise).
        """
        max_attempts = 2
        hard_timeout = 20

        def _do_fetch_sync() -> str:
            if source_type == "youtube":
                result = extract_youtube(url)
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "YouTube extraction failed"))
                return result.text
            elif source_type == "pdf":
                if url.startswith(("http://", "https://")):
                    result = extract_url(url)
                    if result.source_type == "error":
                        raise ValueError(result.metadata.get("error", "PDF URL extraction failed"))
                    return result.text
                else:
                    from pathlib import Path

                    from llmwikify.foundation.extractors.pdf import extract_pdf
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

        last_error = None
        for attempt in range(max_attempts):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_do_fetch_sync),
                    timeout=hard_timeout,
                )
            except asyncio.TimeoutError:
                last_error = f"Fetch timed out after {hard_timeout}s: {url}"
                logger.debug("Attempt %d/%d timed out for %s", attempt + 1, max_attempts, url)
            except (ValueError, ConnectionError, OSError) as e:
                last_error = str(e)
                logger.debug("Attempt %d/%d failed for %s: %s", attempt + 1, max_attempts, url, e)

        raise ValueError(last_error or f"Fetch failed after {max_attempts} attempts: {url}")
