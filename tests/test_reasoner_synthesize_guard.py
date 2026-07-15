"""Tests for reasoner guards against stale-state decisions.

Covers:
- LLM returning 'synthesize' when synthesis already exists
- LLM returning 'plan' when report already exists
- synthesis_exists in vars_dict
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from llmwikify.apps.chat.state import ResearchState
from llmwikify.apps.research.reasoner import ResearchReasoner


def _make_engine():
    """Minimal mock engine for reasoner tests."""
    engine = type("Engine", (), {})()
    engine.db = type("DB", (), {
        "get_sources": lambda self, sid: [
            {"id": "src1", "analysis": {"status": "ok"}},
        ]
    })()
    engine.config = {"max_replan_attempts": 2}
    engine._action_ctx = type("Ctx", (), {})()
    engine._max_replan = 2
    return engine


def _state(**overrides) -> ResearchState:
    """Build a ResearchState with sensible defaults."""
    s = ResearchState(session_id="s1", query="test", max_rounds=15)
    s.clarification = {"clarified": True}
    s.sub_queries = [{"id": "sq1", "query": "q1"}]
    s.sources = [{"id": "src1", "sub_query_id": "sq1", "analysis": {"status": "ok"}}]
    s.round = 3
    s.budget_remaining = 0.5
    s.synthesis = {"knowledge_gaps": [], "contradictions": []}
    s.knowledge_gaps = []
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_llm_synthesize_when_synthesis_exists_falls_back():
    """LLM returning 'synthesize' when synthesis exists → rule_based fallback."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(synthesis={"key": "val"}, knowledge_gaps=[], report_md=None)

    # Patch run_prompt at the reasoner module level (local binding)
    with patch.object(
        reasoner._engine._action_ctx.__class__,
        "__call__",
        return_value=None,
    ):
        pass  # Just need to patch run_prompt in reasoner's namespace

    # Direct approach: patch the function in the reasoner module's globals
    import llmwikify.apps.research.reasoner as mod
    mock_run = AsyncMock(return_value={"action": "synthesize", "thought": "test"})
    old = mod.run_prompt
    mod.run_prompt = mock_run
    try:
        result = await reasoner.reason(state)
    finally:
        mod.run_prompt = old

    assert result == "report"


@pytest.mark.asyncio
async def test_llm_plan_when_report_exists_falls_back():
    """LLM returning 'plan' when report exists → rule_based fallback."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(
        synthesis={"knowledge_gaps": []},
        knowledge_gaps=[],
        report_md="# Report",
        review=None,
    )

    import llmwikify.apps.research.reasoner as mod
    mock_run = AsyncMock(return_value={"action": "plan", "thought": "replan"})
    old = mod.run_prompt
    mod.run_prompt = mock_run
    try:
        result = await reasoner.reason(state)
    finally:
        mod.run_prompt = old

    assert result == "review"


@pytest.mark.asyncio
async def test_vars_dict_includes_synthesis_exists():
    """_llm_reason passes synthesis_exists to the prompt."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(synthesis={"key": "val"})

    import llmwikify.apps.research.reasoner as mod
    mock_run = AsyncMock(return_value={"action": "report", "thought": "time for report"})
    old = mod.run_prompt
    mod.run_prompt = mock_run
    try:
        await reasoner._llm_reason(state)
    finally:
        mod.run_prompt = old

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("synthesis_exists") is True


@pytest.mark.asyncio
async def test_vars_dict_synthesis_exists_false():
    """_llm_reason passes synthesis_exists=False when no synthesis."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(synthesis=None)

    import llmwikify.apps.research.reasoner as mod
    mock_run = AsyncMock(return_value={"action": "report", "thought": "test"})
    old = mod.run_prompt
    mod.run_prompt = mock_run
    try:
        await reasoner._llm_reason(state)
    finally:
        mod.run_prompt = old

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("synthesis_exists") is False


@pytest.mark.asyncio
async def test_rule_based_returns_report_after_synthesis():
    """rule_based correctly returns 'report' when synthesis exists but report doesn't."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(
        synthesis={"knowledge_gaps": [], "contradictions": []},
        knowledge_gaps=[],
        report_md=None,
    )

    result = reasoner.rule_based(state)
    assert result == "report"


@pytest.mark.asyncio
async def test_rule_based_returns_synthesize_when_no_synthesis():
    """rule_based returns 'synthesize' when synthesis is None."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(synthesis=None, knowledge_gaps=[])

    result = reasoner.rule_based(state)
    assert result == "synthesize"


@pytest.mark.asyncio
async def test_rule_based_no_replan_after_synthesis():
    """rule_based skips replan when synthesis exists, even with knowledge_gaps."""
    engine = _make_engine()
    reasoner = ResearchReasoner(engine)
    state = _state(
        synthesis={"knowledge_gaps": ["gap1"]},
        knowledge_gaps=["gap1"],
        budget_remaining=0.8,
        round=0,
        report_md=None,
    )

    result = reasoner.rule_based(state)
    # Should NOT return "plan" even though knowledge_gaps is non-empty
    # and budget is high — synthesis already exists.
    assert result == "report"
