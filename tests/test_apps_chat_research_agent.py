"""Unit tests for the C1 ResearchAgent wrapper.

Per the 4-layer refactor design doc §4 (Sprint C, sub-batch C5.5,
target ~10 tests for the ResearchAgent wrapper).

ResearchAgent subclasses ChatBase and composes ResearchEngine.
The tests exercise the chat-style interface (research() sync,
aresearch() async, astream_research() async generator) and
the prompt-heuristic routing in astream().

We don't exercise the full 6-step research pipeline (that's
covered by tests/test_autoresearch.py and tests/test_apps_chat_*
for the engine itself). Here we just verify the wrapper.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llmwikify.apps.chat.research_engine.engine import ResearchEngine
from llmwikify.apps.chat.research_agent import ResearchAgent


# ─── Stubs ────────────────────────────────────────────────────────


class StubLLM:
    """Minimal LLM stub. Used to construct ResearchEngine without I/O."""

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def chat(self, messages, **kw) -> str:
        self.calls.append(messages)
        return "stub-reply"


# ─── Construction ───────────────────────────────────────────────


class TestResearchAgentConstruction:
    def _make_custom_engine(self) -> ResearchEngine:
        """Build a ResearchEngine that doesn't need a real wiki/db.

        We use ``object.__new__`` to skip the real ``__init__`` and
        set the minimal attributes the tests poke at. The
        research_agent.py only calls ``self.engine.research``,
        ``self.engine.aresearch``, and ``self.engine.astream_research``,
        so we only need those attributes.
        """
        engine = object.__new__(ResearchEngine)
        engine.llm_client = StubLLM()
        return engine

    def test_with_custom_engine(self) -> None:
        llm = StubLLM()
        engine = self._make_custom_engine()
        agent = ResearchAgent(llm_client=llm, engine=engine)
        assert agent.engine is engine
        assert "research" in agent._default_system_prompt.lower()

    def test_custom_system_prompt(self) -> None:
        llm = StubLLM()
        engine = self._make_custom_engine()
        agent = ResearchAgent(
            llm_client=llm, engine=engine, system_prompt="Custom instructions"
        )
        assert agent._default_system_prompt == "Custom instructions"

    def test_subclass_of_chat_base(self) -> None:
        """ResearchAgent is a ChatBase subclass (gets ask/astream/...)."""
        from llmwikify.apps.chat.base import ChatBase
        assert issubclass(ResearchAgent, ChatBase)

    @pytest.mark.skip(reason="v0.38: register_tool / tools dict removed")
    def test_inherits_tools_dict(self) -> None:
        """Tools registered on the agent are stored in the ChatBase dict."""
        llm = StubLLM()
        engine = self._make_custom_engine()
        agent = ResearchAgent(llm_client=llm, engine=engine)
        agent.register_tool("my_tool", lambda: 1)
        assert "my_tool" in agent.tools


# ─── Sync research() backward compat ───────────────────────────


class TestResearchAgentSync:
    def test_research_delegates_to_engine(self) -> None:
        """The sync .research() is the backward-compat shim for the
        pre-async autoresearch interface. It drives the engine's
        async ``run`` via ``asyncio.run``."""
        llm = StubLLM()
        engine = object.__new__(ResearchEngine)
        engine.llm_client = llm
        agent = ResearchAgent(llm_client=llm, engine=engine)

        # Stub the engine's async run() method
        called: list[dict] = []
        async def fake_run(query, **kw):
            called.append({"q": query, **kw})
            yield {"type": "report", "text": "fake report"}

        agent.engine.run = fake_run  # type: ignore[method-assign]

        out = agent.research("what is X?", max_steps=3)
        # The return shape is {"report": ..., "steps": [...]}
        assert out["report"] == "fake report"
        # And the engine's run() was called with the right args
        assert called == [{"q": "what is X?", "max_steps": 3}]


# ─── Heuristic for research-style prompts ─────────────────────


class TestResearchAgentLooksLikeResearch:
    @pytest.mark.parametrize("prompt,expected", [
        ("What is the capital of France?", False),  # plain Q&A
        ("Can you research the history of X?", True),
        ("Please investigate this issue", True),
        ("Compare A and B", True),
        ("Analyze the trade-offs", True),
        ("Give me a survey of the literature", True),
        ("Write a literature review on X", True),
    ])
    def test_heuristic(self, prompt: str, expected: bool) -> None:
        assert ResearchAgent._looks_like_research(prompt) is expected

    def test_heuristic_is_case_insensitive(self) -> None:
        assert ResearchAgent._looks_like_research("RESEARCH this") is True
        assert ResearchAgent._looks_like_research("Research this") is True


# ─── Async astream() routing ───────────────────────────────────


class TestResearchAgentAstreamRouting:
    """``astream()`` routes research-style prompts to the engine and
    plain Q&A to the parent's streaming LLM call."""

    def _make_agent(self) -> tuple[ResearchAgent, list[dict]]:
        llm = StubLLM()
        engine = object.__new__(ResearchEngine)
        engine.llm_client = llm
        agent = ResearchAgent(llm_client=llm, engine=engine)
        calls: list[dict] = []

        async def fake_run(query, **kw):
            calls.append({"query": query, **kw})
            yield {"type": "step", "step": "plan"}
            yield {"type": "report_chunk", "text": "hello "}
            yield {"type": "report_chunk", "text": "world"}

        agent.engine.run = fake_run  # type: ignore[method-assign]
        return agent, calls

    def test_astream_routes_research_prompt(self) -> None:
        agent, calls = self._make_agent()
        chunks: list[str] = []
        async def collect() -> None:
            async for c in agent.astream("Research the history of X"):
                chunks.append(c)
        asyncio.run(collect())
        # The engine's report_chunks were emitted
        assert chunks == ["hello ", "world"]
        # And the engine's run was called exactly once
        assert len(calls) == 1
        assert calls[0]["query"] == "Research the history of X"

    def test_astream_routes_plain_qa_to_chat_base(self) -> None:
        """Non-research prompts fall back to ChatBase.astream()."""
        llm = StubLLM()
        engine = object.__new__(ResearchEngine)
        engine.llm_client = llm
        agent = ResearchAgent(llm_client=llm, engine=engine)

        # Patch engine.run to be a sentinel — it should
        # NOT be called for non-research prompts.
        called: list[str] = []
        async def fake_run(query, **kw):
            called.append(query)
            yield {"type": "report_chunk", "text": "should-not-appear"}
        agent.engine.run = fake_run  # type: ignore[method-assign]

        # Patch llm_client.chat to be sync (no astream_chat)
        def fake_chat(messages, **kw):
            return "direct-llm-reply"
        agent.llm_client.chat = fake_chat  # type: ignore[method-assign]

        chunks: list[str] = []
        async def collect() -> None:
            async for c in agent.astream("What is 2+2?"):
                chunks.append(c)
        asyncio.run(collect())
        # The LLM's plain reply is yielded
        assert chunks == ["direct-llm-reply"]
        # And the engine was NOT called
        assert called == []
