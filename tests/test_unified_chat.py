"""Tests for unified/handlers/ — ChatReasoner + ToolActor (mock LLM)。"""
from __future__ import annotations

import json
from typing import Any

import pytest

from llmwikify.apps.chat.agent.unified.core import StepResult, StreamingHandler
from llmwikify.apps.chat.agent.unified.spec import ActResult, ChatSpec, ReasonResponse

# ── Mock LLM service ──────────────────────────────────────


class _StubLLMService:
    """Stub chat_service for ChatReasoner tests."""

    def __init__(self, stream_events: list[dict] | None = None):
        self._stream_events = stream_events or []
        self.config: dict = {}

    async def _llm_stream_with_retry(self, messages, tools):
        for ev in self._stream_events:
            yield ev


class _StubExecutor:
    """Stub tool_executor for ToolActor tests.

    ToolActor._execute_tool calls executor.execute(tool_name, args, tool_registry, session_id, ctx)
    using positional args.
    """

    def __init__(self, results: dict[str, Any] | None = None):
        self.results = results or {}
        self.calls: list[tuple] = []

    async def execute(self, *args, **kwargs):
        # Accept both positional and keyword args
        tool_name = args[0] if args else kwargs.get("tool_name", "")
        self.calls.append(tool_name)
        if tool_name in self.results:
            return self.results[tool_name]
        return {"status": "ok", "tool": tool_name}


# ── ChatReasoner ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_reasoner_yields_events():
    from llmwikify.apps.chat.agent.unified.handlers.chat_reasoner import ChatReasoner

    # LLM returns done with content (TextModeParser will parse it as content)
    service = _StubLLMService([
        {"type": "done", "content": "Hello world"},
    ])
    reasoner = ChatReasoner(chat_service=service)
    spec = ChatSpec(messages=[{"role": "user", "content": "hi"}])

    events = []
    response = None
    async for event in reasoner.stream(spec.messages, spec, None):
        if isinstance(event, StepResult):
            response = event.output
        else:
            events.append(event)

    assert response is not None
    assert isinstance(response, ReasonResponse)
    assert response.raw_content == "Hello world"


@pytest.mark.asyncio
async def test_chat_reasoner_no_tools():
    from llmwikify.apps.chat.agent.unified.handlers.chat_reasoner import ChatReasoner

    service = _StubLLMService([
        {"type": "done", "content": "simple answer"},
    ])
    reasoner = ChatReasoner(chat_service=service)
    spec = ChatSpec(messages=[{"role": "user", "content": "hi"}])

    response = None
    async for event in reasoner.stream(spec.messages, spec, None):
        if isinstance(event, StepResult):
            response = event.output

    assert response is not None
    assert response.tool_calls == []
    assert response.raw_content == "simple answer"


# ── ToolActor ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_actor_success():
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

    executor = _StubExecutor(results={"wiki_read": {"status": "ok", "content": "page content"}})
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": {"page_name": "test"}},
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    events = []
    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output
        else:
            events.append(event)

    assert result is not None
    assert isinstance(result, ActResult)
    assert result.success is True
    assert len(result.messages_to_inject) == 1
    assert result.messages_to_inject[0]["role"] == "tool"

    # Should have TOOL_CALL_START and TOOL_CALL_END events
    start_events = [e for e in events if e.get("type") == "tool_call_start"]
    end_events = [e for e in events if e.get("type") == "tool_call_end"]
    assert len(start_events) == 1
    assert len(end_events) == 1


@pytest.mark.asyncio
async def test_tool_actor_empty_name():
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

    actor = ToolActor(tool_executor=_StubExecutor())
    response = ReasonResponse(tool_calls=[{"name": "", "args": {}}])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    events = []
    async for event in actor.stream(response, spec, None):
        if not isinstance(event, StepResult):
            events.append(event)

    error_events = [e for e in events if e.get("type") == "tool_call_error"]
    assert len(error_events) == 1
    assert "empty name" in error_events[0]["error"]


@pytest.mark.asyncio
async def test_tool_actor_tool_error():
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

    executor = _StubExecutor()
    # Override execute to raise
    async def failing_execute(*args, **kwargs):
        raise RuntimeError("tool exploded")
    executor.execute = failing_execute

    actor = ToolActor(tool_executor=executor)
    response = ReasonResponse(tool_calls=[{"name": "bad_tool", "args": {}}])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    events = []
    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output
        else:
            events.append(event)

    error_events = [e for e in events if e.get("type") == "tool_call_error"]
    assert len(error_events) == 1
    assert "exploded" in error_events[0]["error"]


@pytest.mark.asyncio
async def test_tool_actor_confirmation():
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

    executor = _StubExecutor(results={
        "wiki_write": {"status": "confirmation_required", "confirmation_id": "abc123", "impact": {}},
    })
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[{"name": "wiki_write", "args": {"page": "test"}}])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output

    assert result is not None
    assert result.needs_confirmation is True
    assert result.tool_name == "wiki_write"


@pytest.mark.asyncio
async def test_tool_actor_no_tool_calls():
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

    actor = ToolActor(tool_executor=_StubExecutor())
    response = ReasonResponse(tool_calls=[])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output

    assert result is not None
    assert result.success is True
    assert result.messages_to_inject == []
