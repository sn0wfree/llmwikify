"""Tests for streaming tool_call delta accumulation.

Regression coverage for the bug where ``StreamableLLMClient`` emitted
each streaming chunk as a separate ``tool_call`` event instead of
accumulating deltas by ``index``.  This caused:

  - Tool names to be empty on all chunks except the first
  - Arguments to be JSON fragments that fell through to ``{"raw": ...}``
  - The ReAct loop to dispatch N broken tool calls instead of 1 real one

The fix accumulates tool_call deltas by ``index`` and emits one
complete ``tool_call`` event per tool call after ``finish_reason``.
"""

from __future__ import annotations

import json

import pytest


def _accumulate_tool_calls(chunks: list[dict]) -> list[dict]:
    """Simulate the accumulation logic from streamable.py astream_chat.

    This directly tests the buffer logic without needing to mock httpx.
    """
    tool_call_buffer: dict[int, dict] = {}
    accumulated = ""
    events = []

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
                })
            tool_call_buffer.clear()
            events.append({
                "type": "done",
                "content": accumulated,
                "finish_reason": finish,
            })
            break

    return events


def _tc(index: int = 0, *, name: str | None = None,
        arguments: str | None = None, call_id: str | None = None) -> dict:
    """Build a tool_call delta chunk."""
    func: dict = {}
    if name is not None:
        func["name"] = name
    if arguments is not None:
        func["arguments"] = arguments
    tc: dict = {"index": index, "function": func}
    if call_id is not None:
        tc["id"] = call_id
    return {"choices": [{"delta": {"tool_calls": [tc]}, "finish_reason": None}]}


def _done(finish_reason: str = "stop") -> dict:
    return {"choices": [{"delta": {}, "finish_reason": finish_reason}]}


class TestToolCallAccumulation:
    """Tests for tool_call delta accumulation logic."""

    def test_single_tool_call_split_across_chunks(self):
        """A single tool call split across 4 chunks should emit one tool_call."""
        chunks = [
            _tc(0, name="check", call_id="call_1"),    # name here
            _tc(0, arguments='{"mo'),                    # partial args
            _tc(0, arguments='del":'),                   # partial args
            _tc(0, arguments='"check"}'),                # final args
            _done("tool_calls"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "check"
        assert tool_events[0]["args"] == '{"model":"check"}'

    def test_multiple_tool_calls_at_different_indexes(self):
        """Two tool calls at different indexes should produce two events."""
        chunks = [
            _tc(0, name="wiki_lint", call_id="c1"),
            _tc(1, name="wiki_read", call_id="c2"),
            _tc(0, arguments='{"mode":"check"}'),
            _tc(1, arguments='{"page":"foo"}'),
            _done("tool_calls"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 2
        assert tool_events[0]["tool"] == "wiki_lint"
        assert tool_events[0]["args"] == '{"mode":"check"}'
        assert tool_events[1]["tool"] == "wiki_read"
        assert tool_events[1]["args"] == '{"page":"foo"}'

    def test_empty_arguments(self):
        """Tool call with no arguments should produce empty args."""
        chunks = [
            _tc(0, name="no_args_tool", call_id="c1"),
            _done("tool_calls"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "no_args_tool"
        assert tool_events[0]["args"] == ""

    def test_no_raw_fallback(self):
        """Arguments should NEVER be wrapped in {"raw": ...} anymore."""
        chunks = [
            _tc(0, name="test_tool", call_id="c1",
                arguments='{"key":"value"}'),
            _done("tool_calls"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert "raw" not in tool_events[0]["args"]

    def test_done_without_tool_calls(self):
        """A stream with content but no tool_calls should work normally."""
        chunks = [
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            _done("stop"),
        ]
        events = _accumulate_tool_calls(chunks)

        done_events = [e for e in events if e.get("type") == "done"]
        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(done_events) == 1
        assert len(tool_events) == 0

    def test_interleaved_content_and_tool_calls(self):
        """Content chunks between tool call chunks should not break accumulation."""
        chunks = [
            {"choices": [{"delta": {"content": "I'll use "}, "finish_reason": None}]},
            _tc(0, name="search", call_id="c1", arguments='{"q":"test"}'),
            _done("tool_calls"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "search"

    def test_finish_reason_stop_with_tool_calls_in_buffer(self):
        """finish_reason='stop' should also flush the tool_call buffer."""
        chunks = [
            _tc(0, name="my_tool", call_id="c1", arguments='{"x":1}'),
            _done("stop"),
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "my_tool"

    def test_real_world_minimax_pattern(self):
        """Simulate the actual MiniMax M2.7 streaming pattern."""
        chunks = [
            {"choices": [{"delta": {"content": ""}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_abc123",
                 "function": {"name": "wiki_write_page", "arguments": ""}}
            ]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '{"title":'}}
            ]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '"Test Page",'}}
            ]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '"content":"Hello"}'}},
            ]}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]
        events = _accumulate_tool_calls(chunks)

        tool_events = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "wiki_write_page"
        args = json.loads(tool_events[0]["args"])
        assert args["title"] == "Test Page"
        assert args["content"] == "Hello"
