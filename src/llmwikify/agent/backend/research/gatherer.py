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

    async def gather(self, sub_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Gather content for all sub-queries with controlled parallelism.

        Returns list of SSE events to yield.
        """
        max_parallel = self.config.get("max_parallel_gathering", 5)
        semaphore = asyncio.Semaphore(max_parallel)
        events: list[dict[str, Any]] = []

        async def process_one(sq: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                return await self._gather_one(sq)

        tasks = [process_one(sq) for sq in sub_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                events.append({"type": "sub_query_failed", "error": str(r)})
            elif r is not None:
                events.append(r)

        return events

    async def _gather_one(self, sub_query: dict[str, Any]) -> dict[str, Any] | None:
        """Gather content for a single sub-query."""
        sq_id = sub_query["id"]
        source_type = sub_query["source_type"]
        url = sub_query.get("url", "")
        query = sub_query["query"]
        session_id = self.session_manager.session_id

        try:
            content: str = ""

            # For web/youtube without URL, search first
            if source_type in ("web", "youtube") and not url:
                from .web_search import WebSearch
                searcher = WebSearch(self.config)
                if source_type == "youtube":
                    results = await searcher.search(f"site:youtube.com {query}", num_results=1)
                else:
                    results = await searcher.search(query, num_results=1)
                if results:
                    url = results[0].url
                    sub_query["url"] = url

            if source_type == "wiki":
                pages = self.wiki.search(query, limit=3)
                if pages:
                    page_content = self.wiki.page_io.read_page(pages[0].get("name", query))
                    if isinstance(page_content, str):
                        content = page_content
                    else:
                        content = str(page_content) if page_content else ""
            elif source_type == "youtube" and url:
                result = extract_youtube(url)
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "YouTube extraction failed"))
                content = result.text
            elif source_type == "pdf" and url:
                from pathlib import Path
                from ....extractors.pdf import extract_pdf
                result = extract_pdf(Path(url))
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "PDF extraction failed"))
                content = result.text
            elif source_type == "web" and url:
                result = extract_url(url)
                if result.source_type == "error":
                    raise ValueError(result.metadata.get("error", "Web extraction failed"))
                content = result.text
            else:
                raise ValueError(f"Unsupported source_type={source_type} or missing URL")

            content = content[: self._max_content]
            preview = content[:500]
            title = url or query

            source_id = self.session_manager.add_source(
                session_id=session_id,
                sub_query_id=sq_id,
                source_type=source_type,
                url=url,
                title=title,
                content_length=len(content),
                content_preview=preview,
            )
            self.session_manager.complete_sub_query(sq_id, {"content_length": len(content)})

            return {
                "type": "source_gathered",
                "source_id": source_id,
                "source_type": source_type,
                "title": title,
                "url": url,
            }

        except Exception as e:
            logger.warning("Gather failed for sub_query %s (%s): %s", sq_id, source_type, e)
            self.session_manager.fail_sub_query(sq_id, str(e))
            return {
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": str(e),
            }
