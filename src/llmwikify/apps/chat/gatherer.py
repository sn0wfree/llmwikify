"""Parallel source gathering with semaphore-controlled concurrency."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.db import AutoResearchDatabase
from llmwikify.apps.chat.harness.source_filter import SourceFilter
from llmwikify.apps.chat.session import ResearchSessionManager
from llmwikify.foundation.extractors.web import extract_url
from llmwikify.foundation.extractors.youtube import extract_youtube

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared context passed to every strategy
# ---------------------------------------------------------------------------

@dataclass
class GatherContext:
    """Shared state for a single sub-query gather operation."""
    sq: dict[str, Any]
    seen_urls: set[str]
    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Strategy base class + 4 implementations
# ---------------------------------------------------------------------------

class SourceStrategy(ABC):
    """Base class for source-type gathering strategies."""

    @abstractmethod
    def can_handle(self, sq: dict[str, Any], gatherer: SourceGatherer) -> bool:
        """Return True if this strategy handles the given sub-query."""

    @abstractmethod
    async def gather(self, ctx: GatherContext, gatherer: SourceGatherer) -> None:
        """Execute the gathering. Append results to ctx.events."""


class WikiStrategy(SourceStrategy):
    """Gather from local wiki pages."""

    def can_handle(self, sq: dict[str, Any], gatherer: SourceGatherer) -> bool:
        return sq["source_type"] == "wiki"

    async def gather(self, ctx: GatherContext, gatherer: SourceGatherer) -> None:
        sq = ctx.sq
        sq_id = sq["id"]
        query = sq["query"]
        num_results = gatherer.config.get("web_search_results_per_query", 5)

        pages = gatherer.wiki.search(query, limit=min(num_results, 5))
        for page in pages[:num_results]:
            try:
                page_name = page.get("name", query)
                wiki_url = f"wiki://{page_name}"
                if gatherer._normalize_url(wiki_url) in ctx.seen_urls:
                    continue
                page_content = gatherer.wiki.read_page(page_name)
                content = str(page_content) if page_content else ""
                if not content:
                    continue
                content = content[: gatherer._max_content]
                gatherer._add_source(ctx, sq_id, "wiki", wiki_url, page_name, content)
            except Exception as e:
                logger.warning("Wiki page read failed for %s: %s", page.get("name"), e)

        if ctx.events:
            gatherer.session_manager.complete_sub_query(sq_id, {"sources_count": len(ctx.events)})
        else:
            raise ValueError(f"No wiki pages found for: {query}")


class WebSearchStrategy(SourceStrategy):
    """Gather via web search (web/youtube without URL).

    Optionally runs parallel wiki search when configured.
    """

    def can_handle(self, sq: dict[str, Any], gatherer: SourceGatherer) -> bool:
        return sq["source_type"] in ("web", "youtube") and not sq.get("url")

    async def gather(self, ctx: GatherContext, gatherer: SourceGatherer) -> None:
        sq = ctx.sq
        sq_id = sq["id"]
        source_type = sq["source_type"]
        query = sq["query"]
        num_results = gatherer.config.get("web_search_results_per_query", 5)

        # Search for URLs
        urls_to_fetch = await self._search_urls(gatherer, sq_id, source_type, query, num_results, ctx.seen_urls)

        # Parallel wiki search (web only)
        do_parallel = (
            source_type == "web"
            and gatherer.config.get("parallel_wiki_search", True)
        )
        wiki_pages: list[dict] = []
        if do_parallel:
            try:
                wiki_pages = gatherer.wiki.search(query, limit=min(3, num_results))
            except Exception as e:
                logger.debug("Parallel wiki search failed: %s", e)

        # Fetch web content
        if urls_to_fetch:
            await self._fetch_web_content(gatherer, ctx, sq_id, source_type, query, urls_to_fetch)

        # Gather local wiki results (parallel path)
        if do_parallel and wiki_pages:
            self._gather_wiki_pages(gatherer, ctx, sq_id, wiki_pages, query)

        if ctx.events:
            gatherer.session_manager.complete_sub_query(sq_id, {"sources_count": len(ctx.events)})
        else:
            raise ValueError(f"No results found for: {query}")

    async def _search_urls(
        self,
        gatherer: SourceGatherer,
        sq_id: str,
        source_type: str,
        query: str,
        num_results: int,
        seen_urls: set[str],
    ) -> list[str]:
        """Search for URLs via WebSearch, returning unseen URLs."""
        from llmwikify.apps.research.web_search import WebSearch

        searcher = WebSearch(gatherer.config)
        search_query = f"site:youtube.com {query}" if source_type == "youtube" else query
        logger.info(
            "Gather sub_query %s (%s): invoking WebSearch for %r (num_results=%d)",
            sq_id, source_type, query, num_results,
        )
        try:
            search_results = await asyncio.wait_for(
                searcher.search(search_query, num_results=num_results),
                timeout=15,
            )
            logger.info("Gather sub_query %s: WebSearch returned %d results", sq_id, len(search_results))
        except asyncio.TimeoutError:
            logger.warning("Gather sub_query %s: WebSearch timed out for %r", sq_id, query)
            raise ValueError(f"Search timed out for: {query}") from None

        urls = []
        for r in search_results:
            if r.url and gatherer._normalize_url(r.url) not in seen_urls:
                urls.append(r.url)
        if not urls:
            logger.warning(
                "Gather sub_query %s: WebSearch returned 0 new URLs for %r",
                sq_id, query,
            )
            raise ValueError(f"No new search results for: {query}")
        return urls

    async def _fetch_web_content(
        self,
        gatherer: SourceGatherer,
        ctx: GatherContext,
        sq_id: str,
        source_type: str,
        query: str,
        urls_to_fetch: list[str],
    ) -> None:
        """Fetch web content for each URL and add to context."""
        tasks = [gatherer._fetch_url(source_type, u) for u in urls_to_fetch]
        contents = await asyncio.gather(*tasks, return_exceptions=True)
        for fetch_url, content in zip(urls_to_fetch, contents, strict=False):
            if isinstance(content, Exception):
                logger.warning("Fetch failed for %s: %s", fetch_url, content)
                continue
            if not content:
                continue
            if gatherer._normalize_url(fetch_url) in ctx.seen_urls:
                continue
            content = str(content)[: gatherer._max_content]
            # Apply source filter
            source_candidate = {
                "url": fetch_url, "content": content,
                "source_type": source_type, "title": fetch_url,
            }
            kept, _ = gatherer._source_filter.filter_sources([source_candidate], query)
            if not kept:
                logger.debug("Source filtered out: %s", fetch_url)
                continue
            gatherer._add_source(ctx, sq_id, source_type, fetch_url, fetch_url, content)

    def _gather_wiki_pages(
        self,
        gatherer: SourceGatherer,
        ctx: GatherContext,
        sq_id: str,
        wiki_pages: list[dict],
        query: str,
    ) -> None:
        """Add wiki pages from parallel search to context."""
        for page in wiki_pages[:3]:
            try:
                page_name = page.get("page_name", query)
                wiki_url = f"wiki://{page_name}"
                if gatherer._normalize_url(wiki_url) in ctx.seen_urls:
                    continue
                page_content = gatherer.wiki.read_page(page_name)
                content = str(page_content) if page_content else ""
                if not content:
                    continue
                content = content[: gatherer._max_content]
                gatherer._add_source(ctx, sq_id, "wiki", wiki_url, page_name, content)
            except Exception as e:
                logger.warning("Parallel wiki page read failed for %s: %s", page.get("page_name"), e)


class WebFetchStrategy(SourceStrategy):
    """Gather by directly fetching URLs (web/youtube with URL, or pdf)."""

    def can_handle(self, sq: dict[str, Any], gatherer: SourceGatherer) -> bool:
        # Matches: web/youtube with URL, or any type with urls_to_fetch
        source_type = sq["source_type"]
        url = sq.get("url", "")
        if source_type == "wiki":
            return False
        if source_type in ("web", "youtube") and not url:
            return False  # handled by WebSearchStrategy
        return True  # fallback: try fetching URLs

    async def gather(self, ctx: GatherContext, gatherer: SourceGatherer) -> None:
        sq = ctx.sq
        sq_id = sq["id"]
        source_type = sq["source_type"]
        query = sq["query"]
        url = sq.get("url", "")

        urls_to_fetch: list[str] = []

        if url:
            if gatherer._normalize_url(url) in ctx.seen_urls:
                raise ValueError(f"URL already gathered: {url}")
            urls_to_fetch = [url]

        for fetch_url in urls_to_fetch:
            try:
                content = await gatherer._fetch_url(source_type, fetch_url)
                if not content:
                    continue
                content = content[: gatherer._max_content]
                if gatherer._normalize_url(fetch_url) in ctx.seen_urls:
                    continue
                # Apply source filter
                source_candidate = {
                    "url": fetch_url, "content": content,
                    "source_type": source_type, "title": fetch_url,
                }
                kept, _ = gatherer._source_filter.filter_sources([source_candidate], query)
                if not kept:
                    logger.debug("Source filtered out: %s", fetch_url)
                    continue
                gatherer._add_source(ctx, sq_id, source_type, fetch_url, fetch_url, content)
            except Exception as e:
                logger.warning("Fetch failed for %s: %s", fetch_url, e)

        if ctx.events:
            gatherer.session_manager.complete_sub_query(sq_id, {"sources_count": len(ctx.events)})
        else:
            raise ValueError(f"All fetches failed for: {query}")


# Strategy registry — order matters: first match wins
_STRATEGIES: list[SourceStrategy] = [
    WikiStrategy(),
    WebSearchStrategy(),
    WebFetchStrategy(),
]


# ---------------------------------------------------------------------------
# Main gatherer (orchestrator)
# ---------------------------------------------------------------------------

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
        for prefix in ("http://", "https://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url

    def _add_source(
        self,
        ctx: GatherContext,
        sq_id: str,
        source_type: str,
        url: str,
        title: str,
        content: str,
    ) -> str:
        """Add a source to the session and emit a source_gathered event."""
        ctx.seen_urls.add(self._normalize_url(url))
        source_id = self.session_manager.add_source(
            session_id=ctx.session_id,
            sub_query_id=sq_id,
            source_type=source_type,
            url=url,
            title=title,
            content_length=len(content),
            content_preview=content[:500],
            content=content,
        )
        event = {
            "type": "source_gathered",
            "source_id": source_id,
            "source_type": source_type,
            "title": title,
            "url": url,
        }
        ctx.events.append(event)
        return source_id

    def _select_strategy(self, sq: dict[str, Any]) -> SourceStrategy:
        """Select the first strategy that can handle this sub-query."""
        for strategy in _STRATEGIES:
            if strategy.can_handle(sq, self):
                return strategy
        raise ValueError(f"No strategy for source_type={sq.get('source_type')}")

    async def gather(self, sub_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Gather content for all sub-queries with early-exit optimization.

        Returns list of SSE events to yield. Deduplicates URLs across sub-queries.
        """
        max_parallel = self.config.get("max_parallel_gathering", 8)
        per_query_timeout = 45
        early_exit_threshold = 0.7
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

        tasks = {asyncio.create_task(process_one(sq), name=f"gather-{i}"): sq for i, sq in enumerate(sub_queries)}
        total = len(tasks)
        done_count = 0
        threshold_reached = False
        grace_deadline = None
        last_grace_progress_ts: float = 0.0
        GRACE_PROGRESS_INTERVAL = 5.0

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
                            t.exception()
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
                now = asyncio.get_event_loop().time()
                if not threshold_reached and progress_frac >= early_exit_threshold:
                    threshold_reached = True
                    grace_deadline = now + early_exit_grace
                    last_grace_progress_ts = now
                    logger.info(
                        "Gathering threshold reached: %d/%d done (%.0f%%), grace %ds",
                        done_count, total, progress_frac * 100, early_exit_grace,
                    )
                    events.append({
                        "type": "progress",
                        "phase": "gathering",
                        "completed": done_count,
                        "total": total,
                        "in_grace": True,
                        "grace_remaining_s": early_exit_grace,
                        "message": (
                            f"Threshold reached ({done_count}/{total}), "
                            f"waiting up to {early_exit_grace}s for stragglers"
                        ),
                    })

                if threshold_reached and pending:
                    if now - last_grace_progress_ts >= GRACE_PROGRESS_INTERVAL:
                        last_grace_progress_ts = now
                        remaining = max(0.0, grace_deadline - now)
                        events.append({
                            "type": "progress",
                            "phase": "gathering",
                            "completed": done_count,
                            "total": total,
                            "in_grace": True,
                            "grace_remaining_s": int(remaining),
                            "message": (
                                f"Waiting for {len(pending)} straggler(s) — "
                                f"{int(remaining)}s left"
                            ),
                        })
                    if now >= grace_deadline:
                        logger.info("Grace expired, cancelling %d remaining tasks", len(pending))
                        for t in pending:
                            if not t.done():
                                t.exception()
                                t.cancel()
                        break

        except asyncio.CancelledError:
            logger.warning("Gathering stage cancelled")

        remaining = [t for t in tasks if not t.done()]
        if remaining:
            done, _ = await asyncio.wait(remaining, timeout=5)
            for t in done:
                try:
                    result = t.result()
                    if isinstance(result, list):
                        events.extend(result)
                except Exception:
                    logger.debug("Remaining gather task failed", exc_info=True)

        return events

    async def _gather_one(self, sub_query: dict[str, Any], seen_urls: set[str]) -> list[dict[str, Any]]:
        """Gather content for a single sub-query using the selected strategy."""
        sq_id = sub_query["id"]
        session_id = self.session_manager.session_id
        ctx = GatherContext(sq=sub_query, seen_urls=seen_urls, session_id=session_id)

        try:
            strategy = self._select_strategy(sub_query)
            await strategy.gather(ctx, self)
        except ValueError as e:
            logger.info("Sub-query %s: %s", sq_id, e)
            self.session_manager.fail_sub_query(sq_id, str(e))
            ctx.events.append({
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": str(e),
            })
        except (OSError, ConnectionError) as e:
            logger.warning("Gather network error for %s: %s", sq_id, e)
            self.session_manager.fail_sub_query(sq_id, str(e))
            ctx.events.append({
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": str(e),
            })
        except Exception:
            logger.exception("Unexpected error in gather for %s", sq_id)
            self.session_manager.fail_sub_query(sq_id, "internal error")
            ctx.events.append({
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": "internal error",
            })

        return ctx.events

    async def _fetch_url(self, source_type: str, url: str) -> str:
        """Fetch content from a URL based on source type, with retry and hard timeout."""
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
