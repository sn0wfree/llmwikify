"""Report generation from research synthesis results."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from llmwikify.autoresearch.llm_step import run_prompt
from llmwikify.autoresearch.prompts import source_hash as _source_hash

logger = logging.getLogger(__name__)


class _ReportCtx:
    """Minimal ctx-like object for run_prompt.

    run_prompt needs default_llm, planning_llm, report_llm, config.
    The report generator only has a single LLM client (the report
    one) so the others default to the same client. ``metrics`` is
    optional (None if the caller does not track them).
    """

    def __init__(
        self, llm_client: Any, config: dict[str, Any],
        metrics: Any = None,
    ):
        self.default_llm = llm_client
        self.planning_llm = llm_client
        self.report_llm = llm_client
        self.config = config
        self.metrics = metrics


class ReportGenerator:
    """Generates structured markdown research reports with inline source citations."""

    def __init__(
        self, wiki: Any, llm_client: Any, config: dict[str, Any],
        metrics: Any = None,
    ):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config
        self.metrics = metrics

    def _as_ctx(self) -> _ReportCtx:
        """Build a ctx-like object for run_prompt."""
        return _ReportCtx(self.llm_client, self.config, metrics=self.metrics)

    def _build_source_map(self, sources: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
        """Build hash → source info mapping for inline citations."""
        source_map: dict[str, dict[str, str]] = {}
        for s in sources:
            h = _source_hash(s)
            source_map[h] = {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "source_type": s.get("source_type", ""),
            }
        return source_map

    def _build_source_contents(
        self, sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the per-source content dicts for the YAML template.

        Each entry has: hash, title, source_type, url, content
        (truncated), analysis_summary. Honors the
        ``report_max_per_source`` and ``report_max_total_content``
        config limits.
        """
        max_per_source = self.config.get("report_max_per_source", 4000)
        max_total_content = self.config.get("report_max_total_content", 60000)
        total_content = 0
        source_contents: list[dict[str, Any]] = []
        for s in sources:
            if total_content >= max_total_content:
                break
            full_content = s.get("content") or s.get("content_preview") or ""
            remaining = max_total_content - total_content
            content_limit = min(max_per_source, remaining)
            truncated = full_content[:content_limit]
            total_content += len(truncated)
            source_contents.append({
                "hash": _source_hash(s),
                "title": s.get("title", ""),
                "source_type": s.get("source_type", ""),
                "url": s.get("url", ""),
                "content": truncated,
                "analysis_summary": _summarize_analysis(s.get("analysis", {})),
            })
        return source_contents

    def _build_prompt_kwargs(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
        six_step_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build kwargs for ``run_prompt(\"research_report\", ...)``.

        Centralizes the construction of source_contents + wiki_index
        + six_step_context so both the async ``generate`` and the sync
        streaming fallback can share the same prompt inputs.
        """
        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:5000]
        return {
            "six_step_context": six_step_context,
            "query": query,
            "wiki_index": wiki_index,
            "source_contents": self._build_source_contents(sources),
            "synthesis": synthesis,
        }

    def _build_messages(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
        six_step_context: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Build messages and API params for report generation.

        Kept for backward compatibility with ``generate_streaming``
        (which still calls LLM.stream_chat directly). The non-streaming
        ``generate`` method now uses ``run_prompt`` instead and does
        not call this method.
        """
        from llmwikify.core.prompt_registry import PromptRegistry
        from llmwikify.autoresearch.engine_helpers import resolve_llm_params
        from llmwikify.autoresearch.prompts import render_framework_block

        registry = PromptRegistry(provider=getattr(self.llm_client, "provider", "openai"))
        source_contents = self._build_source_contents(sources)

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

        framework_block = render_framework_block(six_step_context, "report")
        if framework_block:
            messages = [
                {"role": "system", "content": framework_block},
                *messages,
            ]

        llm_params = resolve_llm_params(
            registry, self.config, "research_report", "llm_params",
        )

        return messages, llm_params

    async def generate(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
        six_step_context: dict[str, Any] | None = None,
    ) -> str:
        """Generate a structured markdown report (non-streaming).

        Uses report_model if configured, otherwise falls back to default LLM.
        Source citations use [[Source:hash]] format.
        six_step_context: optional 6-step framework context that augments
        the prompt with structured guidance.

        Migrated to use ``run_prompt`` (commit 4 of the prompt-system
        refactor). The streaming version (``generate_streaming``) still
        uses the lower-level LLM.stream_chat / asyncio.to_thread path
        because it returns an ``Iterator[chunk]`` of the streaming
        response — a fundamentally different interface.
        """
        kwargs = self._build_prompt_kwargs(
            query, sources, synthesis, six_step_context,
        )
        report_md = await run_prompt(
            self._as_ctx(), "research_report", **kwargs,
        )

        # Validate citations
        self._validate_citations(report_md, sources)

        return report_md

    def generate_streaming(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
        six_step_context: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Generate a structured markdown report with streaming output.

        Yields:
            dict: {"type": "progress", "message": str} or
                  {"type": "chunk", "text": str} or
                  {"type": "done", "content": str} or
                  {"type": "error", "error": str}
        """
        messages, llm_params = self._build_messages(query, sources, synthesis, six_step_context)

        # Try streaming first, fall back to non-streaming
        if hasattr(self.llm_client, 'stream_chat'):
            try:
                accumulated = ""
                for chunk in self.llm_client.stream_chat(
                    messages, **llm_params,
                ):
                    if chunk["type"] == "content":
                        accumulated += chunk["text"]
                        yield {"type": "chunk", "text": chunk["text"]}
                    elif chunk["type"] == "thinking":
                        yield {"type": "progress", "message": f"Thinking... ({len(accumulated)} chars)"}
                    elif chunk["type"] == "done":
                        self._validate_citations(accumulated, sources)
                        yield {"type": "done", "content": accumulated}
                        return
            except Exception as e:
                logger.warning("Streaming failed, falling back to non-streaming: %s", e)

        # Fallback: non-streaming (uses run_prompt via asyncio.run)
        import asyncio

        try:
            # Sync generator must NOT be called from a running event loop
            # (would raise RuntimeError on asyncio.run). Verify and fail
            # fast with a clear message rather than the cryptic stack trace.
            try:
                asyncio.get_running_loop()
                raise RuntimeError(
                    "generate_streaming must be called from a thread without "
                    "a running event loop (use asyncio.to_thread)"
                )
            except RuntimeError as e:
                if "no running event loop" not in str(e):
                    raise
            kwargs = self._build_prompt_kwargs(
                query, sources, synthesis, six_step_context,
            )
            report_md = asyncio.run(
                run_prompt(self._as_ctx(), "research_report", **kwargs)
            )
            self._validate_citations(report_md, sources)
            yield {"type": "done", "content": report_md}
        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def _validate_citations(self, report_md: str, sources: list[dict[str, Any]]) -> None:
        """Validate citations in the report."""
        import re
        citations = re.findall(r'\[\[Source:([a-f0-9]+)\]\]', report_md)
        source_hashes = {_source_hash(s) for s in sources}
        invalid = [c for c in citations if c not in source_hashes]
        if invalid:
            logger.warning("Report has %d invalid citations (out of %d total): %s", len(invalid), len(citations), invalid[:5])


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
