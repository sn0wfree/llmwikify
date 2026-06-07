"""End-to-end integration test: ResearchAgent + Harness + golden cases.

Per the 4-layer refactor design doc §4 (Sprint C, sub-batch C5.6,
target: 1 integration test that exercises the new chat
framework end-to-end with a real (in-memory) LLM client).

The test:
1. Builds a fake LLM that returns canned JSON for each of the
   6 research steps (plan, gather, analyze, synthesize,
   report, review).
2. Constructs a ResearchAgent wrapping that LLM.
3. Runs ResearchAgent.research() to completion.
4. Feeds the report into a Harness with one golden case
   ("report mentions 'fake'") to confirm the framework
   composes end-to-end.

We do NOT exercise the real WebSearch/analyzer/reviewer
here — those have their own tests in test_autoresearch.py.
The point here is to confirm the new chat framework
(ResearchAgent → Harness) hangs together.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from llmwikify.apps.chat.engine import ResearchEngine
from llmwikify.apps.chat.harness import GoldenCase, Harness
from llmwikify.apps.chat.research_agent import ResearchAgent


# ─── Fake multi-step LLM ───────────────────────────────────────


class StepLLM:
    """LLM stub that returns a different canned response per call.

    The autoresearch engine makes 6 LLM calls per research
    pass: plan, clarify, gather, analyze, synthesize, report.
    This stub returns a different response for each call so
    the engine can complete a full cycle.
    """

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.call_index = 0

    def chat(self, messages, **kw) -> str:
        self.calls.append([dict(m) if isinstance(m, dict) else {
            "role": m.role, "content": m.content
        } for m in messages])
        idx = self.call_index
        self.call_index += 1

        # First call: plan (returns a list of sub-queries)
        if idx == 0:
            return json.dumps({
                "sub_queries": ["what is X?", "history of X"],
                "rationale": "two complementary angles",
            })
        # Second call: clarification (returns empty clarifications)
        if idx == 1:
            return json.dumps({
                "clarifications": [],
                "final_query": "Tell me about X",
            })
        # Third call: source analysis
        if idx == 2:
            return json.dumps({
                "sources": [
                    {"url": "https://fake.example.com/a", "summary": "X is fake"},
                    {"url": "https://fake.example.com/b", "summary": "More about X"},
                ],
            })
        # Fourth call: synthesis
        if idx == 3:
            return json.dumps({
                "synthesis": "X is a topic of great interest. Here is a fake report.",
            })
        # Fifth call: final report
        if idx == 4:
            return (
                "# Report\n\nX is a topic of great interest. "
                "Here is the FAKE final report about X. "
                "It mentions that X is a fake topic."
            )
        # Any further call: just acknowledge
        return json.dumps({"ack": True})


# ─── Integration test ──────────────────────────────────────────


class TestResearchAgentIntegration:
    def _make_stub_engine(self, llm: Any) -> ResearchEngine:
        """Build a ResearchEngine whose ``run`` returns canned events.

        We use ``object.__new__`` to skip the real ``__init__`` (which
        needs a wiki + db) and just set the attributes that
        ``ResearchAgent`` actually touches (``engine.run``).
        """
        engine = object.__new__(ResearchEngine)
        engine.llm_client = llm

        async def fake_run(query: str, **kwargs: Any):
            yield {"type": "step", "step": "plan", "query": query}
            yield {"type": "step", "step": "gather"}
            yield {"type": "report_chunk", "text": "This is the FAKE report about "}
            yield {"type": "report_chunk", "text": "the topic."}
            yield {"type": "report", "text": "This is the FAKE report about the topic."}

        engine.run = fake_run  # type: ignore[method-assign]
        return engine

    def test_research_then_harness(self) -> None:
        """End-to-end: run a research session, then grade the output
        through the Harness framework."""
        llm = StepLLM()
        engine = self._make_stub_engine(llm)
        agent = ResearchAgent(llm_client=llm, engine=engine)

        # Run the research session (sync, via asyncio.run inside).
        out = agent.research("Tell me about X")
        assert isinstance(out, dict)
        # The report should contain "fake" (from our canned engine).
        report_text = str(out.get("report", ""))
        assert "fake" in report_text.lower()

        # Now feed the report into the Harness.
        h = Harness()
        h.add(GoldenCase(
            name="report_mentions_fake",
            inputs={"query": "X"},
            expected_contains=["FAKE"],
        ))

        async def runner(inputs: dict) -> str:
            return report_text

        report = asyncio.run(h.run(runner))
        assert len(report.results) == 1
        assert report.results[0].passed is True
        assert report.summary() == "1/1 passed (100%)"

    def test_research_via_chat_interface(self) -> None:
        """Smoke test: ``agent.ask()`` from ChatBase still works on a
        ResearchAgent — confirms the inheritance."""
        llm = StepLLM()
        engine = self._make_stub_engine(llm)
        agent = ResearchAgent(llm_client=llm, engine=engine)

        # Plain Q&A via ChatBase.ask() — falls through to the
        # underlying llm_client.chat (the StepLLM).
        out = agent.ask("hello", session=agent.new_session())
        # StepLLM returns json.dumps(...) for every call.
        assert "sub_queries" in out  # it was the first call (idx=0)

    def test_aresearch_returns_dict(self) -> None:
        """The async ``aresearch`` returns the same shape as the sync one."""
        llm = StepLLM()
        engine = self._make_stub_engine(llm)
        agent = ResearchAgent(llm_client=llm, engine=engine)

        out = asyncio.run(agent.aresearch("Tell me about X"))
        assert isinstance(out, dict)
        assert "fake" in str(out.get("report", "")).lower()
