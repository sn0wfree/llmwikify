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

from collections.abc import AsyncIterator
from typing import Any

from .base import ChatBase
from .engine import ResearchEngine


class ResearchAgent(ChatBase):
    """Chat-style wrapper around ``ResearchEngine``.

    Args:
        llm_client: any object with a ``.chat(messages, **kwargs)``
            method. Typically a ``StreamableLLMClient``.
        engine: optional pre-constructed ``ResearchEngine``.
            If None, one is built from the ``llm_client``.
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
        self.engine = engine or ResearchEngine(llm_client=llm_client)

    # ── canonical chat-style interface ─────────────────────

    async def aresearch(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Async-iterate over research events (plan → gather → ...).

        Returns a dict with the final ``report`` and the
        ``steps`` list.
        """
        return await self.engine.aresearch(query, **kwargs)

    async def astream_research(
        self, query: str, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Async-iterate over per-step events as the engine runs."""
        async for event in self.engine.astream_research(query, **kwargs):
            yield event

    # ── backward-compat with ResearchEngine.research() ─────

    def research(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Synchronous, blocking research. Delegates to the engine."""
        return self.engine.research(query, **kwargs)

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
            async for event in self.engine.astream_research(prompt, **kwargs):
                if event.get("type") == "report_chunk":
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
