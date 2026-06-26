"""额外 chat 集成测试 — 基于 test_apps_chat_agent_runner_v2.py 模式。

测试 ChatReasoner + ToolActor 的端到端流程：
- 多工具调用
- 工具错误处理
- 边界情况
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from llmwikify.apps.chat.agent.unified.core import StepResult
from llmwikify.apps.chat.agent.unified.handlers.chat_reasoner import ChatReasoner
from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor
from llmwikify.apps.chat.agent.unified.spec import ActResult, ChatSpec, ReasonResponse


# ── Mock services ─────────────────────────────────────────


class _StubLLMService:
    """Stub chat_service for ChatReasoner tests."""

    def __init__(self, stream_events: list[dict] | None = None):
        self._stream_events = stream_events or []
        self.config: dict = {}

    async def _llm_stream_with_retry(self, messages, tools):
        for ev in self._stream_events:
            yield ev


class _StubExecutor:
    """Stub tool_executor for ToolActor tests."""

    def __init__(self, results: dict[str, Any] | None = None):
        self.results = results or {}
        self.calls: list[tuple] = []

    async def execute(self, *args, **kwargs):
        tool_name = args[0] if args else kwargs.get("tool_name", "")
        self.calls.append(tool_name)
        if tool_name in self.results:
            return self.results[tool_name]
        return {"status": "ok", "tool": tool_name}


# ── ChatReasoner tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_reasoner_done_content_fallback():
    """When parser produces no content, fallback to done content."""
    service = _StubLLMService([
        {"type": "done", "content": "fallback content"},
    ])
    reasoner = ChatReasoner(chat_service=service)
    spec = ChatSpec(messages=[{"role": "user", "content": "hi"}])

    response = None
    async for event in reasoner.stream(spec.messages, spec, None):
        if isinstance(event, StepResult):
            response = event.output

    assert response is not None
    assert response.raw_content == "fallback content"


@pytest.mark.asyncio
async def test_chat_reasoner_empty_llm():
    """LLM returns nothing → empty response."""
    service = _StubLLMService([])
    reasoner = ChatReasoner(chat_service=service)
    spec = ChatSpec(messages=[{"role": "user", "content": "hi"}])

    response = None
    async for event in reasoner.stream(spec.messages, spec, None):
        if isinstance(event, StepResult):
            response = event.output

    assert response is not None
    assert response.raw_content == ""
    assert response.tool_calls == []


@pytest.mark.asyncio
async def test_chat_reasoner_preserves_tool_calls():
    """LLM tool calls are preserved in ReasonResponse."""
    service = _StubLLMService([
        {"type": "done", "content": "I'll search for that."},
    ])
    reasoner = ChatReasoner(chat_service=service)
    spec = ChatSpec(messages=[{"role": "user", "content": "hi"}])

    response = None
    async for event in reasoner.stream(spec.messages, spec, None):
        if isinstance(event, StepResult):
            response = event.output

    assert response is not None
    assert isinstance(response.tool_calls, list)


# ── ToolActor tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_actor_multiple_tools():
    """Multiple tool calls executed sequentially."""
    executor = _StubExecutor(results={
        "read_file": {"status": "ok", "content": "file content"},
        "grep": {"status": "ok", "matches": ["line1", "line2"]},
    })
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[
        {"name": "read_file", "args": {"path": "/test.py"}},
        {"name": "grep", "args": {"pattern": "def ", "path": "/test.py"}},
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
    assert result.success is True
    assert len(result.messages_to_inject) == 2
    assert result.messages_to_inject[0]["name"] == "read_file"
    assert result.messages_to_inject[1]["name"] == "grep"

    start_events = [e for e in events if e.get("type") == "tool_call_start"]
    end_events = [e for e in events if e.get("type") == "tool_call_end"]
    assert len(start_events) == 2
    assert len(end_events) == 2


@pytest.mark.asyncio
async def test_tool_actor_partial_failure():
    """One tool fails, others succeed — partial failure."""
    executor = _StubExecutor(results={
        "read_file": {"status": "ok", "content": "file content"},
    })
    # grep will raise
    async def failing_grep(*args, **kwargs):
        raise RuntimeError("grep exploded")
    original_execute = executor.execute

    async def dispatch(*args, **kwargs):
        tool_name = args[0] if args else kwargs.get("tool_name", "")
        if tool_name == "grep":
            raise RuntimeError("grep exploded")
        return await original_execute(*args, **kwargs)
    executor.execute = dispatch

    actor = ToolActor(tool_executor=executor)
    response = ReasonResponse(tool_calls=[
        {"name": "read_file", "args": {"path": "/test.py"}},
        {"name": "grep", "args": {"pattern": "def "}},
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    events = []
    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output
        else:
            events.append(event)

    # read_file succeeded, grep failed
    assert result is not None
    assert result.success is True
    assert len(result.messages_to_inject) == 1  # only read_file
    assert result.messages_to_inject[0]["name"] == "read_file"

    error_events = [e for e in events if e.get("type") == "tool_call_error"]
    assert len(error_events) == 1
    assert "exploded" in error_events[0]["error"]


@pytest.mark.asyncio
async def test_tool_actor_error_status():
    """Tool returns error status → TOOL_CALL_ERROR event."""
    executor = _StubExecutor(results={
        "wiki_read": {"status": "error", "error": "Page not found"},
    })
    actor = ToolActor(tool_executor=executor)
    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": {"page_name": "nonexistent"}},
    ])
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
    assert "Page not found" in error_events[0]["error"]

    # No messages injected for failed tools
    assert result is not None
    assert result.messages_to_inject == []


@pytest.mark.asyncio
async def test_tool_actor_string_args():
    """Tool args as JSON string → parsed correctly."""
    executor = _StubExecutor()
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": '{"page_name": "test"}'},  # string args
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output

    assert result is not None
    assert result.success is True
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_tool_actor_malformed_args():
    """Tool args as malformed string → fallback to _raw."""
    executor = _StubExecutor()
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": "not json"},  # malformed string
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output

    assert result is not None
    assert result.success is True
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_tool_actor_call_id_generation():
    """Missing call_id → auto-generated."""
    executor = _StubExecutor()
    actor = ToolActor(tool_executor=executor)

    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": {}},  # no id
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    events = []
    async for event in actor.stream(response, spec, None):
        if not isinstance(event, StepResult):
            events.append(event)

    start_events = [e for e in events if e.get("type") == "tool_call_start"]
    assert len(start_events) == 1
    assert "call_id" in start_events[0]
    assert start_events[0]["call_id"].startswith("call_")


@pytest.mark.asyncio
async def test_tool_actor_tool_message_format():
    """Tool messages have correct format for LLM consumption."""
    executor = _StubExecutor(results={
        "wiki_read": {"status": "ok", "content": "page content"},
    })
    actor = ToolActor(tool_executor=executor)
    response = ReasonResponse(tool_calls=[
        {"name": "wiki_read", "args": {"page_name": "test"}, "id": "call_abc123"},
    ])
    spec = ChatSpec(messages=[], tool_registry=None, session_id="test")

    result = None
    async for event in actor.stream(response, spec, None):
        if isinstance(event, StepResult):
            result = event.output

    assert result is not None
    msg = result.messages_to_inject[0]
    assert msg["role"] == "tool"
    assert msg["name"] == "wiki_read"
    assert msg["tool_call_id"] == "call_abc123"
    assert isinstance(msg["content"], str)
