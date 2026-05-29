"""Report generation from research synthesis results."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates structured markdown research reports with inline source citations."""

    def __init__(self, wiki: Any, llm_client: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config

    def _build_source_map(self, sources: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
        """Build hash → source info mapping for inline citations."""
        source_map: dict[str, dict[str, str]] = {}
        for s in sources:
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            source_map[h] = {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "source_type": s.get("source_type", ""),
            }
        return source_map

    async def generate(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
    ) -> str:
        """Generate a structured markdown report.

        Uses report_model if configured, otherwise falls back to default LLM.
        Source citations use [[Source:hash]] format.
        """
        from ....core.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        source_map = self._build_source_map(sources)

        # Build source content summaries for the prompt
        # Limit total content to avoid LLM context window overflow
        max_per_source = 4000  # Reduced from 8000 to fit more sources
        max_total_content = 60000  # Total cap across all sources
        total_content = 0
        source_contents: list[dict[str, Any]] = []
        for s in sources:
            if total_content >= max_total_content:
                break
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            full_content = s.get("content") or s.get("content_preview") or ""
            # Truncate per-source and track total
            remaining = max_total_content - total_content
            content_limit = min(max_per_source, remaining)
            truncated = full_content[:content_limit]
            total_content += len(truncated)
            source_contents.append({
                "hash": h,
                "title": s.get("title", ""),
                "source_type": s.get("source_type", ""),
                "url": s.get("url", ""),
                "content": truncated,
                "analysis_summary": _summarize_analysis(s.get("analysis", {})),
            })

        # Get wiki index for context
        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:5000]

        messages = registry.get_messages(
            "research_report",
            query=query,
            wiki_index=wiki_index,
            source_contents=source_contents,
            synthesis=synthesis,
        )
        api_params = registry.get_api_params("research_report")

        # Call LLM (sync wrapped in async) with retry
        import asyncio
        from .retry import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)
        call_timeout = self.config.get("llm_call_timeout_seconds", 120)

        async def _call_llm() -> str:
            return await asyncio.to_thread(
                self.llm_client.chat, messages,
                max_tokens=api_params.get("max_tokens", 8192),
                temperature=api_params.get("temperature", 0.3),
            )

        report_md = await retry_async(_call_llm, max_attempts=max_attempts, base_delay=2.0, call_timeout=call_timeout)

        # Validate citations
        import re
        citations = re.findall(r'\[\[Source:([a-f0-9]+)\]\]', report_md)
        source_hashes = {
            hashlib.md5((s.get("url") or s.get("title", "")).encode()).hexdigest()[:12]
            for s in sources
        }
        invalid = [c for c in citations if c not in source_hashes]
        if invalid:
            logger.warning("Report has %d invalid citations (out of %d total): %s", len(invalid), len(citations), invalid[:5])

        return report_md


def _summarize_analysis(analysis: dict[str, Any]) -> str:
    """Create a concise summary from an analysis dict."""
    if not analysis or analysis.get("status") in ("error", "skipped"):
        return ""

    parts = []
    if analysis.get("topics"):
        parts.append(f"Topics: {', '.join(analysis['topics'][:5])}")
    if analysis.get("key_facts"):
        facts = analysis["key_facts"][:5]
        parts.append(f"Key facts: {'; '.join(facts)}")
    if analysis.get("claims"):
        claims = [c.get("statement", "") for c in analysis["claims"][:3]]
        parts.append(f"Claims: {'; '.join(claims)}")
    if analysis.get("entities"):
        ents = [e.get("name", "") for e in analysis["entities"][:5]]
        parts.append(f"Entities: {', '.join(ents)}")

    return "\n".join(parts)
