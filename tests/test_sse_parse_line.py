"""Tests for the shared SSE line parser ``_parse_sse_line``.

Covers the pure-function extraction (S-1+S-3) that was previously
duplicated across ``stream_chat`` (sync) and ``astream_chat`` (async).
"""

from __future__ import annotations

import json

import pytest

from llmwikify.foundation.llm.streamable import _parse_sse_line


def _line(data: dict) -> str:
    """Build an SSE ``data:`` line from a chunk dict."""
    return f"data: {json.dumps(data)}"


def _delta_content(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


def _delta_thinking(text: str) -> dict:
    return {"choices": [{"delta": {"reasoning_content": text}, "finish_reason": None}]}


def _delta_tool_call(
    index: int = 0,
    *,
    name: str | None = None,
    arguments: str | None = None,
    call_id: str | None = None,
) -> dict:
    func: dict = {}
    if name is not None:
        func["name"] = name
    if arguments is not None:
        func["arguments"] = arguments
    tc: dict = {"index": index, "function": func}
    if call_id is not None:
        tc["id"] = call_id
    return {"choices": [{"delta": {"tool_calls": [tc]}, "finish_reason": None}]}


def _finish(reason: str = "stop") -> dict:
    return {"choices": [{"delta": {}, "finish_reason": reason}]}


class TestParseSseLineBlankAndDone:
    def test_blank_line_returns_none(self):
        assert _parse_sse_line("", "", {}) is None

    def test_done_yields_done_event(self):
        result = _parse_sse_line("[DONE]", "hello", {})
        assert result is not None
        events, acc, chunk = result
        assert len(events) == 1
        assert events[0] == {"type": "done", "content": "hello"}
        assert acc == "hello"
        assert chunk is None

    def test_data_prefix_stripped(self):
        line = _line(_delta_content("world"))
        result = _parse_sse_line(line, "", {})
        assert result is not None
        events, acc, _ = result
        assert events[0] == {"type": "content", "text": "world"}
        assert acc == "world"

    def test_malformed_json_returns_none(self):
        assert _parse_sse_line("data: {bad json", "", {}) is None

    def test_non_data_line_returns_none(self):
        assert _parse_sse_line("event: heartbeat", "", {}) is None


class TestParseSseLineContent:
    def test_single_content(self):
        result = _parse_sse_line(_line(_delta_content("hi")), "", {})
        assert result is not None
        events, acc, _ = result
        assert events == [{"type": "content", "text": "hi"}]
        assert acc == "hi"

    def test_content_accumulates(self):
        buf: dict[int, dict] = {}
        acc = ""
        r1 = _parse_sse_line(_line(_delta_content("hel")), acc, buf)
        assert r1 is not None
        _, acc, _ = r1
        r2 = _parse_sse_line(_line(_delta_content("lo")), acc, buf)
        assert r2 is not None
        events, acc, _ = r2
        assert acc == "hello"
        assert events == [{"type": "content", "text": "lo"}]

    def test_empty_content_delta_skipped(self):
        chunk = {"choices": [{"delta": {"content": ""}, "finish_reason": None}]}
        assert _parse_sse_line(_line(chunk), "", {}) is None


class TestParseSseLineThinking:
    def test_thinking_event(self):
        result = _parse_sse_line(_line(_delta_thinking("reason")), "", {})
        assert result is not None
        events, _, _ = result
        assert events == [{"type": "thinking", "text": "reason"}]

    def test_thinking_not_accumulated(self):
        buf: dict[int, dict] = {}
        r = _parse_sse_line(_line(_delta_thinking("thought")), "", buf)
        assert r is not None
        _, acc, _ = r
        assert acc == ""


class TestParseSseLineToolCalls:
    def test_single_tool_call_split(self):
        """Single tool call accumulated across 3 chunks + finish."""
        buf: dict[int, dict] = {}
        acc = ""
        # Intermediate tool_call deltas produce no events (buffered)
        r1 = _parse_sse_line(_line(_delta_tool_call(0, name="run", call_id="c1")), acc, buf)
        assert r1 is None  # buffered, no events yet
        r2 = _parse_sse_line(_line(_delta_tool_call(0, arguments='{"x":')), acc, buf)
        assert r2 is None
        r3 = _parse_sse_line(_line(_delta_tool_call(0, arguments='1}')), acc, buf)
        assert r3 is None
        # finish_reason flushes the buffer
        r4 = _parse_sse_line(_line(_finish("tool_calls")), acc, buf)
        assert r4 is not None
        events, _, _ = r4
        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "run"
        assert tool_events[0]["args"] == '{"x":1}'
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1

    def test_multiple_tool_calls(self):
        """Two tool calls at different indexes."""
        buf: dict[int, dict] = {}
        # Intermediate deltas: None (buffered)
        assert _parse_sse_line(_line(_delta_tool_call(0, name="a", call_id="c1")), "", buf) is None
        assert _parse_sse_line(_line(_delta_tool_call(1, name="b", call_id="c2")), "", buf) is None
        # Finish flushes both
        r3 = _parse_sse_line(_line(_finish("tool_calls")), "", buf)
        assert r3 is not None
        events, _, _ = r3
        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) == 2
        assert tool_events[0]["tool"] == "a"
        assert tool_events[1]["tool"] == "b"

    def test_no_tool_calls_on_stop(self):
        """finish_reason=stop with empty buffer produces only done."""
        result = _parse_sse_line(_line(_finish("stop")), "hello", {})
        assert result is not None
        events, _, _ = result
        assert len(events) == 1
        assert events[0]["type"] == "done"
        assert events[0]["finish_reason"] == "stop"

    def test_length_finish_flushes(self):
        """finish_reason=length also flushes tool calls."""
        buf: dict[int, dict] = {}
        assert _parse_sse_line(_line(_delta_tool_call(0, name="t", call_id="c1")), "", buf) is None
        result = _parse_sse_line(_line(_finish("length")), "", buf)
        assert result is not None
        events, _, _ = result
        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) == 1


class TestParseSseLineChunkReturn:
    def test_chunk_returned_for_normal_line(self):
        chunk = _delta_content("x")
        result = _parse_sse_line(_line(chunk), "", {})
        assert result is not None
        _, _, returned_chunk = result
        assert returned_chunk == chunk

    def test_chunk_none_for_done(self):
        result = _parse_sse_line("[DONE]", "", {})
        assert result is not None
        _, _, chunk = result
        assert chunk is None
