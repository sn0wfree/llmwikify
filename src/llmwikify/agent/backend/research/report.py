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
        source_map = self._build_source_map(sources)

        # Build source content summaries for the prompt
        source_contents: list[dict[str, Any]] = []
        for s in sources:
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            # Prefer full content over preview, allow up to 8000 chars per source in report
            full_content = s.get("content") or s.get("content_preview") or ""
            source_contents.append({
                "hash": h,
                "title": s.get("title", ""),
                "source_type": s.get("source_type", ""),
                "url": s.get("url", ""),
                "content": full_content[:8000],
                "analysis_summary": _summarize_analysis(s.get("analysis", {})),
            })

        # Get wiki index for context
        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:5000]

        # Build prompt
        system = """You are a research report writer. Generate a comprehensive, well-structured markdown report based on multiple gathered sources and their analysis.

Rules:
- Start with a clear H1 heading that captures the research topic
- Use H2/H3 headings to organize subtopics
- Include an Executive Summary section
- Use bullet points and lists where appropriate
- Reference sources using [[Source:hash]] format (e.g., [[Source:abc123def456]])
- End with a "References" section listing all sources with their full URLs
- Write minimum 800 words
- Distinguish verified facts from unverified claims
- Note contradictions between sources when they exist
- Use English for the report content"""

        user_parts = [f"# Research Topic: {query}\n"]

        if wiki_index:
            user_parts.append(f"## Existing Wiki Context\n{wiki_index}\n")

        user_parts.append("## Gathered Sources\n")
        for sc in source_contents:
            user_parts.append(f"### Source [{sc['hash']}] — {sc['source_type'].upper()}")
            user_parts.append(f"Title: {sc['title']}")
            if sc['url']:
                user_parts.append(f"URL: {sc['url']}")
            user_parts.append(f"Content:\n{sc['content']}\n")
            if sc['analysis_summary']:
                user_parts.append(f"Analysis:\n{sc['analysis_summary']}\n")

        if synthesis.get("reinforced_claims"):
            user_parts.append("## Cross-Source Synthesis")
            user_parts.append(f"- Reinforced claims: {len(synthesis['reinforced_claims'])}")
            user_parts.append(f"- Contradictions: {len(synthesis.get('contradictions', []))}")
            user_parts.append(f"- Knowledge gaps: {len(synthesis.get('knowledge_gaps', []))}")
            user_parts.append(f"- New entities: {len(synthesis.get('new_entities', []))}")
            user_parts.append("")

        user_parts.append(
            "Generate the research report now. Use [[Source:hash]] for citations."
        )

        user_msg = "\n".join(user_parts)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        # Call LLM (sync wrapped in async) with retry
        import asyncio
        from .retry import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)

        async def _call_llm() -> str:
            return await asyncio.to_thread(
                self.llm_client.chat, messages, max_tokens=8192, temperature=0.3
            )

        report_md = await retry_async(_call_llm, max_attempts=max_attempts, base_delay=2.0)
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
