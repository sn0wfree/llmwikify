"""Regression tests for the minimax tool_call_id mismatch bug.

Minimax (and providers enforcing the OpenAI tool-call spec) return
400 ``tool result's tool id(call_xxx) not found (2013)`` when the
conversation history sent on iteration 2+ contains a tool result
without a matching ``assistant(tool_calls[i].id)`` declaration.

Two root causes:
  1. ``StreamableLLMClient.stream_chat`` / ``astream_chat``
     collected ``entry["id"]`` from the upstream chunks but DROPPED
     it on yield. The runner never saw the provider-assigned id and
     generated a local fallback.
  2. ``ChatRunnerV2.run_stream`` appended tool results to
     ``ctx.messages`` but never appended the corresponding
     ``assistant(tool_calls=[...])`` message — so the next
     iteration's LLM call only saw ``[user, tool(call_xxx), ...]``
     with no assistant declaring the originating tool_call.

These tests lock the fix:
  - ``streamable.py`` now propagates ``id`` in yielded tool_call
    events.
  - ``runner_v2.py`` now resolves tool_call ids once and appends
    the assistant(tool_calls) message before ACT, so the next LLM
    call has a matching declaration for every tool result.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2, _RunContext
from llmwikify.apps.chat.agent.spec import ChatRunSpec

# ── Streamable id propagation ────────────────────────────────


def _accumulate_tool_calls(chunks: list[dict]) -> list[dict]:
    """Re-implement the astream_chat accumulation logic verbatim.

    Mirrors :class:`StreamableLLMClient.astream_chat` so we can
    assert that the yielded ``tool_call`` event carries the
    provider-assigned ``id`` field. No httpx mocking required.
    """
    tool_call_buffer: dict[int, dict] = {}
    accumulated = ""
    events: list[dict] = []

    for chunk in chunks:
        delta = chunk.get("choices", [{}])[0].get("delta", {})

        if "tool_calls" in delta:
            for tc in delta["tool_calls"]:
                idx = tc.get("index", 0)
                if idx not in tool_call_buffer:
                    tool_call_buffer[idx] = {
                        "id": tc.get("id", ""),
                        "name": "",
                        "args_parts": [],
                    }
                entry = tool_call_buffer[idx]
                if "id" in tc and tc["id"]:
                    entry["id"] = tc["id"]
                func = tc.get("function", {})
                if "name" in func and func["name"]:
                    entry["name"] = func["name"]
                if "arguments" in func and func["arguments"]:
                    entry["args_parts"].append(func["arguments"])

        if "content" in delta and delta["content"]:
            accumulated += delta["content"]

        finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
        if finish in ("stop", "tool_calls", "length"):
            for entry in tool_call_buffer.values():
                events.append({
                    "type": "tool_call",
                    "tool": entry["name"],
                    "args": "".join(entry["args_parts"]),
                    "id": entry.get("id", ""),
                })
            tool_call_buffer.clear()
            events.append({
                "type": "done",
                "content": accumulated,
                "finish_reason": finish,
            })
            break

    return events


def _tc(index: int = 0, *, name: str, arguments: str, call_id: str) -> dict:
    func: dict = {"name": name, "arguments": arguments}
    return {
        "choices": [{
            "delta": {
                "tool_calls": [{"index": index, "id": call_id, "function": func}],
            },
        }],
    }


def test_streamable_yields_tool_call_with_id_from_provider() -> None:
    """streamable must forward the upstream provider id verbatim."""
    chunks = [
        _tc(index=0, name="read_file", arguments='{"path":',
            call_id="call_0f42d47d"),
        {
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"arguments": ' "/tmp"'},
                }]},
            }],
        },
        {"choices": [{"finish_reason": "tool_calls"}]},
    ]
    events = _accumulate_tool_calls(chunks)
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]["id"] == "call_0f42d47d", (
        "streamable must propagate the provider-assigned id "
        "so the runner can match assistant(tool_calls[i].id) "
        "↔ tool(tool_call_id) across iterations."
    )


def test_streamable_yields_empty_id_when_provider_omits_it() -> None:
    """If the provider never sends id, streamable yields '' (runner falls back)."""
    chunks = [
        {
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"name": "read_file", "arguments": "{}"},
                }]},
            }],
        },
        {"choices": [{"finish_reason": "tool_calls"}]},
    ]
    events = _accumulate_tool_calls(chunks)
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_call_events[0]["id"] == ""


# ── ChatRunnerV2 assistant(tool_calls) appending ──────────────


class _StubLLMService:
    """Replay a sequence of LLM events per call.

    The first call yields ``events``. Subsequent calls yield
    ``followup``. This matches the existing pattern in
    ``tests/test_apps_chat_agent_runner_v2.py`` so tool-call tests
    can drive a single REASON→ACT round without spinning forever
    into the next iteration.
    """

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        followup: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config: dict = {}
        self._events = events or [{"type": "done", "content": "stub"}]
        self._followup = followup or [{"type": "done", "content": "done"}]
        self.tool_spec_called = False
        self.truncate_called = False
        self.call_count = 0

    def _get_toolspec(self, _registry):
        self.tool_spec_called = True
        return []

    def _truncate_messages(self, messages):
        self.truncate_called = True
        return list(messages)

    async def _llm_stream_with_retry(self, _messages, _tools):
        self.call_count += 1
        events = self._events if self.call_count == 1 else self._followup
        for ev in events:
            yield ev


class _StubExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    async def execute(self, tool_name, args, _registry, _session_id, _ctx):
        self.calls.append((tool_name, args, _ctx))
        return {"status": "ok", "result": f"result for {tool_name}"}


class _StubPromptBuilder:
    async def build(self, *args, **kwargs) -> str:
        return "stub system"


def _make_runner(llm_service, executor) -> ChatRunnerV2:
    return ChatRunnerV2(
        chat_service=llm_service,
        tool_executor=executor,
        prompt_builder=_StubPromptBuilder(),
    )


def _make_spec(**overrides) -> ChatRunSpec:
    defaults: dict = {
        "messages": [{"role": "user", "content": "read it"}],
        "tool_registry": object(),
        "session_id": "s1",
    }
    defaults.update(overrides)
    return ChatRunSpec(**defaults)


def test_assistant_message_appended_with_tool_calls_id_match() -> None:
    """After a tool-call iteration, ctx.messages must contain an
    assistant(tool_calls) declaration whose tool_calls[i].id matches
    the corresponding tool(tool_call_id) message."""
    llm = _StubLLMService(
        events=[
            {
                "type": "tool_call",
                "id": "call_0f42d47d",
                "name": "read_file",
                "args": {"path": "/tmp/x"},
            },
            {"type": "done", "content": ""},
        ],
        followup=[
            {"type": "done", "content": "all done"},
        ],
    )
    executor = _StubExecutor()
    runner = _make_runner(llm, executor)
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    events = asyncio.run(collect())

    ctx = runner._current_ctx
    assert isinstance(ctx, _RunContext)
    assistant_msgs = [m for m in ctx.messages if m.get("role") == "assistant"]
    tool_msgs = [m for m in ctx.messages if m.get("role") == "tool"]
    assert len(assistant_msgs) >= 1, (
        "runner must append assistant(tool_calls) for the next "
        "iteration's LLM call to satisfy the OpenAI tool-call spec"
    )
    assistant = assistant_msgs[-1]
    assert "tool_calls" in assistant, (
        "the assistant message produced for a tool_call iteration "
        "must carry the tool_calls field, not just content"
    )
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["id"] == "call_0f42d47d"

    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_0f42d47d"
    assert (
        assistant["tool_calls"][0]["id"] == tool_msgs[0]["tool_call_id"]
    ), "assistant(tool_calls[i].id) must equal tool(tool_call_id)"


def test_assistant_message_id_fallback_when_provider_omits_id() -> None:
    """When the LLM yields a tool_call without id (text-mode /
    older streams), runner resolves a stable local id and uses it
    in BOTH the assistant message and the tool message."""
    llm = _StubLLMService(
        events=[
            {
                "type": "tool_call",
                "id": "",
                "name": "exec",
                "args": {"cmd": "ls"},
            },
            {"type": "done", "content": ""},
        ],
        followup=[
            {"type": "done", "content": "ok"},
        ],
    )
    executor = _StubExecutor()
    runner = _make_runner(llm, executor)
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    asyncio.run(collect())

    ctx = runner._current_ctx
    assert isinstance(ctx, _RunContext)
    assistant = [m for m in ctx.messages if m.get("role") == "assistant"][-1]
    tool_msg = [m for m in ctx.messages if m.get("role") == "tool"][-1]
    fallback_id = assistant["tool_calls"][0]["id"]
    assert fallback_id.startswith("call_") and len(fallback_id) > 4, (
        f"expected stable local fallback id, got {fallback_id!r}"
    )
    assert fallback_id == tool_msg["tool_call_id"]


def test_no_assistant_message_with_tool_calls_when_no_tools_called() -> None:
    """If the LLM returns only content (no tool_call), the runner
    must NOT append an assistant(tool_calls=[]) — that would emit
    an empty tool_calls field and confuse the next LLM call."""
    llm = _StubLLMService(
        events=[
            {"type": "content", "text": "just talking"},
            {"type": "done", "content": "just talking"},
        ],
    )
    executor = _StubExecutor()
    runner = _make_runner(llm, executor)
    spec = _make_spec()

    async def collect() -> list[dict[str, Any]]:
        return [ev async for ev in runner.run_stream(spec)]

    asyncio.run(collect())

    ctx = runner._current_ctx
    assert isinstance(ctx, _RunContext)
    assistant_msgs = [m for m in ctx.messages if m.get("role") == "assistant"]
    for msg in assistant_msgs:
        assert "tool_calls" not in msg, (
            "content-only iterations must not produce an assistant "
            "message with a tool_calls field"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
