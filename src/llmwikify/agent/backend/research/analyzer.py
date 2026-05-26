"""Source content analysis using Wiki.analyze_source()."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

from ..db import AgentDatabase
from .session import ResearchSessionManager

logger = logging.getLogger(__name__)


class SourceAnalyzer:
    """Analyzes gathered sources using Wiki.analyze_source()."""

    def __init__(self, wiki: Any, session_manager: ResearchSessionManager, config: dict[str, Any]):
        self.wiki = wiki
        self.session_manager = session_manager
        self.config = config

    async def analyze_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze all sources. Returns SSE events."""
        events: list[dict[str, Any]] = []

        for src in sources:
            if src.get("analysis"):
                continue  # already analyzed

            try:
                analysis = await asyncio.to_thread(self._analyze_one, src)
                self.session_manager.update_source_analysis(src["id"], analysis)
                events.append({
                    "type": "source_analyzed",
                    "source_id": src["id"],
                    "title": src.get("title", ""),
                })
            except Exception as e:
                logger.warning("Analysis failed for source %s: %s", src["id"], e)
                events.append({
                    "type": "source_analysis_failed",
                    "source_id": src["id"],
                    "error": str(e),
                })

        return events

    def _analyze_one(self, source: dict[str, Any]) -> dict[str, Any]:
        """Analyze a single source using Wiki.analyze_source().

        Writes content to raw/ if not already there, then calls wiki.
        """
        content = source.get("content_preview", "") or ""
        if not content:
            return {"status": "skipped", "reason": "No content"}

        # Write to raw/ for wiki to analyze
        url_or_title = source.get("url") or source.get("title", "unknown")
        content_hash = hashlib.md5(url_or_title.encode()).hexdigest()[:12]
        raw_dir = self.wiki.root / "raw" / "research"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{content_hash}.txt"
        raw_path.write_text(content[: self.config.get("max_source_content_length", 500000)])

        rel_path = f"raw/research/{content_hash}.txt"
        try:
            analysis = self.wiki.analyze_source(rel_path)
            return analysis
        except Exception as e:
            logger.warning("wiki.analyze_source failed for %s: %s", rel_path, e)
            return {"status": "error", "reason": str(e)}
