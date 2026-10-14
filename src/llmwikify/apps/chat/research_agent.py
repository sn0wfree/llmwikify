"""ResearchAgent — thin ChatBase wrapper around the research engine.

This is the **public** chat-style entry point for the 6-step
research engine that used to live in ``llmwikify.autoresearch``.
It composes:

- ``ChatBase`` (this package) for the session/tool plumbing
- ``ResearchEngine`` (``engine.py``) for the 6-step
  research loop
- ``StreamableLLMClient`` (``foundation.llm.streamable``)
  for the underlying LLM

The class is intentionally thin: it doesn't re-implement
the research loop. Its job is to expose a chat-style API
(``await agent.aresearch(query)``) and to keep
backward-compat with callers that used the old
``ResearchEngine.research(query)`` signature.

Per the design doc §3.5, this file is **~50 LOC** of
adapter code; the real research logic remains in
``engine.py``.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

# Lazy import: ResearchEngine lives in llmwikify.apps.research.engine.
# Use lazy local import inside __init__ to avoid circular dependency
# (research_engine.engine imports chat.__init__ which imports this file).
# TYPE_CHECKING guard keeps the type annotation resolvable by
# typing.get_type_hints() (PEP 563 alone would lazy-eval the string but
# any introspecting tool would still fail to resolve the name).

if TYPE_CHECKING:
    from llmwikify.apps.research.engine import ResearchEngine

from .base import ChatBase


class ResearchAgent(ChatBase):
    """Chat-style wrapper around ``ResearchEngine``.

    Args:
        llm_client: any object with a ``.chat(messages, **kwargs)``
            method. Typically a ``StreamableLLMClient``.
        engine: pre-constructed ``ResearchEngine``. Required in practice:
            ResearchEngine needs ``wiki`` + ``db``, so the wrapper cannot
            build one from ``llm_client`` alone (passing ``None`` raises
            ``TypeError`` with guidance).
        system_prompt: default system prompt prepended to
            every session.
    """

    def __init__(
        self,
        llm_client: Any,
        engine: ResearchEngine | None = None,
        system_prompt: str = (
            "You are a research assistant. Investigate the user's "
            "query by searching the web, gathering sources, "
            "synthesizing findings, and reporting a final answer."
        ),
    ) -> None:
        super().__init__(llm_client=llm_client, system_prompt=system_prompt)
        if engine is None:
            # 2026-10-14 fix (Bug 3): the llm_client-only fallback built
            # ResearchEngine(llm_client=...) which has been missing the
            # now-required wiki/db args since the v0.40 apps/research
            # migration (commit 91ef936); every such construction raised a
            # bare TypeError. Fail fast with an actionable message instead.
            raise TypeError(
                "ResearchAgent requires an explicit `engine=...`: "
                "ResearchEngine needs wiki + db. Build "
                "ResearchEngine(wiki=..., db=..., llm_client=...) and pass it in."
            )
        self.engine = engine

    # ── canonical chat-style interface ─────────────────────

    async def aresearch(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Async-run the research engine and return the final report.

        Drains the engine's async event stream (``engine.run``)
        into a final dict with ``{"report": ..., "steps": [...]}``.
        """
        steps: list[dict[str, Any]] = []
        report_text: str = ""
        async for event in self.engine.run(query, **kwargs):
            steps.append(dict(event))
            if event.get("type") == "report":
                report_text = str(event.get("text", ""))
        return {"report": report_text, "steps": steps}

    async def astream_research(
        self, query: str, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Async-iterate over per-step events as the engine runs."""
        async for event in self.engine.run(query, **kwargs):
            yield event

    # ── backward-compat with the original sync research() API ─

    def research(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Synchronous, blocking research.

        Drives the engine's async ``run`` via ``asyncio.run``
        and returns the same shape as ``aresearch`` (dict with
        ``report`` and ``steps``). For backward compat with the
        pre-async ``autoresearch.ResearchEngine.research`` API
        that external callers may still use.
        """
        return asyncio.run(self.aresearch(query, **kwargs))

    # ── ChatBase overrides ────────────────────────────────

    async def astream(
        self,
        prompt: str,
        session: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a research report as it's built.

        For simple Q&A, falls back to the parent's behavior
        (single LLM call). For research-style prompts
        (those that look like a research question), routes
        through the engine.
        """
        if self._looks_like_research(prompt):
            async for event in self.engine.run(prompt, **kwargs):
                if event.get("type") == "report_chunk":
                    yield event.get("text", "")
                elif event.get("type") == "report":
                    yield event.get("text", "")
        else:
            async for chunk in super().astream(prompt, session=session, **kwargs):
                yield chunk

    @staticmethod
    def _looks_like_research(prompt: str) -> bool:
        """Heuristic: prompt looks like a research query."""
        lowered = prompt.lower()
        return any(
            kw in lowered
            for kw in (
                "research",
                "investigate",
                "compare",
                "analyze the",
                "survey of",
                "literature review",
            )
        )
