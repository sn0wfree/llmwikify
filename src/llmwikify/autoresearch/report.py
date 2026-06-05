"""Report generation from research synthesis results."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
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

    def _build_messages(
        self,
        query: str,
        sources: list[dict[str, Any]],
        synthesis: dict[str, Any],
        six_step_context: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Build messages and API params for report generation.

        six_step_context is the consolidated framework output (from
        ResearchState). It includes: clarification, reasoning_check,
        structure_check, evidence_scores. When provided, the report
        prompt is enriched with structured framework guidance so the
        final report follows the 6-step structure.
        """
        from llmwikify.core.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        source_map = self._build_source_map(sources)

        # Build source content summaries for the prompt
        max_per_source = self.config.get("report_max_per_source", 4000)
        max_total_content = self.config.get("report_max_total_content", 60000)
        total_content = 0
        source_contents: list[dict[str, Any]] = []
        for s in sources:
            if total_content >= max_total_content:
                break
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            full_content = s.get("content") or s.get("content_preview") or ""
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

        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:5000]

        # ─── 6-step framework enrichment (step 5: conclusion output) ─
        framework_block = self._render_framework_block(six_step_context)

        messages = registry.get_messages(
            "research_report",
            query=query,
            wiki_index=wiki_index,
            source_contents=source_contents,
            synthesis=synthesis,
        )

        # Inject 6-step framework context as a system-side message if present
        if framework_block:
            messages = [
                {"role": "system", "content": framework_block},
                *messages,
            ]

        from llmwikify.autoresearch.engine_helpers import resolve_llm_params
        llm_params = resolve_llm_params(
            registry, self.config, "research_report", "llm_params",
        )

        return messages, llm_params

    def _render_framework_block(self, six_step_context: dict[str, Any] | None) -> str:
        """Render the 6-step framework context as a system-prompt block.

        Only emitted when the framework was actually run (i.e. all 5
        pre-output steps are present). Format is a numbered checklist
        so the LLM treats it as concrete instructions.
        """
        if not six_step_context:
            return ""
        clarification = six_step_context.get("clarification") or {}
        reasoning = six_step_context.get("reasoning_check") or {}
        structure = six_step_context.get("structure_check") or {}
        evidence_scores = six_step_context.get("evidence_scores") or {}

        # Skip if no framework data at all
        if not (clarification.get("context") or reasoning or structure):
            return ""

        lines = ["# 6-step Framework Guidance (this report should reflect all 6 steps)\n"]

        # Step 1: clarification
        if clarification.get("context"):
            lines.append("## 步骤 1: 概念澄清")
            lines.append(f"- 上下文: {clarification.get('context', '')[:200]}")
            if clarification.get("boundaries"):
                lines.append(f"- 边界: {clarification['boundaries'][:200]}")
            if clarification.get("position"):
                lines.append(f"- 立场: {clarification['position'][:200]}")
            premises = clarification.get("premises") or []
            if premises:
                lines.append(f"- 前提 ({len(premises)}): {'; '.join(str(p)[:80] for p in premises[:5])}")
            lines.append("")

        # Step 2-3: evidence & reasoning
        if evidence_scores:
            avg_ev = (
                sum(evidence_scores.values()) / max(1, len(evidence_scores))
                if isinstance(evidence_scores, dict)
                else 0
            )
            lines.append("## 步骤 2: 建立依据")
            lines.append(f"- 平均证据分: {avg_ev:.2f}")
            lines.append("")

        if reasoning.get("aggregate_score") is not None:
            lines.append("## 步骤 3: 推理严密")
            lines.append(f"- 推理聚合分: {reasoning['aggregate_score']:.2f}")
            per_dim = reasoning.get("scores") or {}
            for dim, score in list(per_dim.items())[:3]:
                lines.append(f"  - {dim}: {score:.2f}")
            lines.append("")

        # Step 4: structure
        if structure.get("aggregate_score") is not None:
            lines.append("## 步骤 4: 稳固结构")
            lines.append(f"- 结构聚合分: {structure['aggregate_score']:.2f}")
            per_layer = structure.get("scores") or {}
            for layer, score in per_layer.items():
                lines.append(f"  - {layer}: {score:.2f}")
            lines.append("")

        # Steps 5 & 6 are the report and review themselves
        lines.append("## 步骤 5: 结论输出（你正在写）")
        lines.append("- 输出结构化 markdown 报告")
        lines.append("- 每个结论引用证据（[[Source:hash]] 格式）")
        lines.append("- 量化不确定性（可能/likely/approximately）")
        lines.append("")
        lines.append("## 步骤 6: 检查清单（评审阶段会执行）")
        lines.append("- 概念是否清晰？边界是否明确？")
        lines.append("- 证据是否充分？推理是否严密？")
        lines.append("- 结构是否稳固？结论是否量化？")
        return "\n".join(lines)

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
        """
        messages, llm_params = self._build_messages(query, sources, synthesis, six_step_context)

        # Call LLM (sync wrapped in async) with retry
        import asyncio
        from llmwikify.autoresearch.retry_managers import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)
        call_timeout = self.config.get("llm_call_timeout_seconds", 120)

        async def _call_llm() -> str:
            return await asyncio.to_thread(
                self.llm_client.chat, messages, **llm_params,
            )

        report_md = await retry_async(_call_llm, max_attempts=max_attempts, base_delay=2.0, call_timeout=call_timeout)

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

        # Fallback: non-streaming
        import asyncio
        from llmwikify.autoresearch.retry_managers import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)
        call_timeout = self.config.get("llm_call_timeout_seconds", 120)

        async def _call_llm() -> str:
            return await asyncio.to_thread(
                self.llm_client.chat, messages, **llm_params,
            )

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
            report_md = asyncio.run(
                retry_async(_call_llm, max_attempts=max_attempts, base_delay=2.0, call_timeout=call_timeout)
            )
            self._validate_citations(report_md, sources)
            yield {"type": "done", "content": report_md}
        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def _validate_citations(self, report_md: str, sources: list[dict[str, Any]]) -> None:
        """Validate citations in the report."""
        import re
        citations = re.findall(r'\[\[Source:([a-f0-9]+)\]\]', report_md)
        source_hashes = {
            hashlib.md5((s.get("url") or s.get("title", "")).encode()).hexdigest()[:12]
            for s in sources
        }
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
