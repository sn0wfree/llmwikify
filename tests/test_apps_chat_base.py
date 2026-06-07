"""Unit tests for the C1 chat framework: ChatBase, ChatMessage, ChatSession.

Per the 4-layer refactor design doc §4 (Sprint C, sub-batch C5.3,
target ~20 tests for ChatBase).

The tests use a stub LLM client (no real network calls). The
point is to exercise the session/tool/streaming mechanics
of ``ChatBase``, not the underlying LLM client itself.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from llmwikify.apps.chat.base import ChatBase, ChatMessage, ChatSession


# ─── Stubs ────────────────────────────────────────────────────────


class StubLLM:
    """Minimal LLM stub that records calls and returns canned text."""

    def __init__(self, reply: str = "stub-reply", raise_on_call: Exception | None = None) -> None:
        self.reply = reply
        self.raise_on_call = raise_on_call
        # We snapshot the messages list to capture what the LLM
        # actually saw at call time. Convert ChatMessage (or dict)
        # to plain dicts so the snapshot is stable.
        self.calls: list[list[dict[str, str]]] = []
        self.temperature: float | None = None

    @staticmethod
    def _snapshot(messages: list[Any]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, dict):
                out.append(dict(m))
            else:
                # ChatMessage dataclass
                out.append({
                    "role": m.role,
                    "content": m.content,
                    "name": m.name,
                    "tool_call_id": m.tool_call_id,
                })
        return out

    def chat(self, messages: list[Any], **kwargs: Any) -> str:
        self.calls.append(self._snapshot(messages))
        self.temperature = kwargs.get("temperature")
        if self.raise_on_call:
            raise self.raise_on_call
        return self.reply


class StubStreamingLLM:
    """Stub LLM that supports ``astream_chat``."""

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks or ["hello", " ", "world"]
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return "".join(self.chunks)

    async     def astream_chat(self, messages: list[Any], **kwargs: Any) -> AsyncIterator[str]:
        snapshot = StubLLM._snapshot(messages)
        for c in self.chunks:
            yield c
        self.calls.append(snapshot)


# ─── ChatMessage dataclass ───────────────────────────────────────


class TestChatMessage:
    def test_defaults(self) -> None:
        m = ChatMessage(role="user", content="hi")
        assert m.role == "user"
        assert m.content == "hi"
        assert m.name is None
        assert m.tool_call_id is None
        assert m.tool_calls == []

    def test_tool_message(self) -> None:
        m = ChatMessage(
            role="tool",
            content='{"result": 42}',
            name="search",
            tool_call_id="call_123",
        )
        assert m.role == "tool"
        assert m.name == "search"
        assert m.tool_call_id == "call_123"

    def test_tool_calls_field_is_independent_per_instance(self) -> None:
        """Dataclass mutable default pitfall: each instance has its own list."""
        m1 = ChatMessage(role="user", content="x")
        m2 = ChatMessage(role="user", content="y")
        m1.tool_calls.append({"id": "1"})
        assert m2.tool_calls == []


# ─── ChatSession ────────────────────────────────────────────────


class TestChatSession:
    def test_empty_session(self) -> None:
        s = ChatSession()
        assert s.system_prompt == ""
        assert s.messages == []

    def test_add_returns_message(self) -> None:
        s = ChatSession()
        m = s.add("user", "hi")
        assert isinstance(m, ChatMessage)
        assert s.messages == [m]

    def test_add_passes_kwargs(self) -> None:
        s = ChatSession()
        m = s.add("tool", "x", name="search", tool_call_id="c1")
        assert m.name == "search"
        assert m.tool_call_id == "c1"


# ─── ChatBase construction ──────────────────────────────────────


class TestChatBaseConstruction:
    def test_minimal_construction(self) -> None:
        stub = StubLLM()
        cb = ChatBase(llm_client=stub, system_prompt="sys")
        assert cb.llm_client is stub
        assert cb._default_system_prompt == "sys"
        assert cb.tools == {}

    def test_default_system_prompt_empty(self) -> None:
        cb = ChatBase(llm_client=StubLLM())
        assert cb._default_system_prompt == ""

    def test_tools_is_a_copy(self) -> None:
        """``tools`` property should return a copy, not the live dict."""
        cb = ChatBase(llm_client=StubLLM())
        snap = cb.tools
        snap["fake"] = 1
        assert "fake" not in cb.tools


# ─── session helpers ────────────────────────────────────────────


class TestChatBaseNewSession:
    def test_new_session_uses_default_system_prompt(self) -> None:
        cb = ChatBase(llm_client=StubLLM(), system_prompt="default")
        s = cb.new_session()
        assert s.system_prompt == "default"

    def test_new_session_overrides_system_prompt(self) -> None:
        cb = ChatBase(llm_client=StubLLM(), system_prompt="default")
        s = cb.new_session(system_prompt="override")
        assert s.system_prompt == "override"

    def test_new_session_returns_fresh_session(self) -> None:
        cb = ChatBase(llm_client=StubLLM())
        s1 = cb.new_session()
        s2 = cb.new_session()
        assert s1 is not s2
        s1.add("user", "x")
        assert s2.messages == []


# ─── tool registration ──────────────────────────────────────────


class TestChatBaseRegisterTool:
    def test_register_and_retrieve(self) -> None:
        cb = ChatBase(llm_client=StubLLM())

        def my_tool(x: int) -> int:
            return x * 2

        cb.register_tool("double", my_tool)
        assert "double" in cb.tools
        assert cb.tools["double"] is my_tool

    def test_register_overwrites(self) -> None:
        cb = ChatBase(llm_client=StubLLM())
        cb.register_tool("t", lambda: 1)
        cb.register_tool("t", lambda: 2)
        assert cb.tools["t"]() == 2


# ─── ask() ──────────────────────────────────────────────────────


class TestChatBaseAsk:
    def test_ask_returns_reply(self) -> None:
        stub = StubLLM(reply="the answer is 42")
        cb = ChatBase(llm_client=stub)
        out = cb.ask("what is 6*7?")
        assert out == "the answer is 42"

    def test_ask_passes_kwargs_to_llm(self) -> None:
        stub = StubLLM()
        cb = ChatBase(llm_client=stub)
        cb.ask("hi", temperature=0.3, max_tokens=64)
        assert stub.temperature == 0.3

    def test_ask_appends_user_and_assistant(self) -> None:
        stub = StubLLM()
        cb = ChatBase(llm_client=stub, system_prompt="be brief")
        s = cb.new_session()
        cb.ask("hi", session=s)
        assert [m.role for m in s.messages] == ["system", "user", "assistant"]
        assert s.messages[0].content == "be brief"
        assert s.messages[1].content == "hi"
        assert s.messages[2].content == "stub-reply"

    def test_ask_without_session_creates_one(self) -> None:
        """Each ask() uses a fresh session (so second call doesn't see first)."""
        stub = StubLLM()
        cb = ChatBase(llm_client=stub, system_prompt="S")
        cb.ask("first")
        cb.ask("second")
        # Each call gets its own session with system+user (2 msgs).
        assert len(stub.calls) == 2
        assert len(stub.calls[0]) == 2
        assert len(stub.calls[1]) == 2

    def test_ask_with_persistent_session_accumulates_history(self) -> None:
        """When the same session is reused, the LLM sees the full history."""
        stub = StubLLM()
        cb = ChatBase(llm_client=stub, system_prompt="S")
        s = cb.new_session()
        cb.ask("first", session=s)
        cb.ask("second", session=s)
        # First call: system+user (2 msgs).
        # Second call: system+user+assistant+user (4 msgs — full history).
        assert len(stub.calls[0]) == 2
        assert len(stub.calls[1]) == 4
        assert stub.calls[0][0]["role"] == "system"
        assert stub.calls[1][0]["role"] == "system"
        assert stub.calls[1][-1]["role"] == "user"

    def test_ask_propagates_llm_exception(self) -> None:
        stub = StubLLM(raise_on_call=RuntimeError("LLM down"))
        cb = ChatBase(llm_client=stub)
        with pytest.raises(RuntimeError, match="LLM down"):
            cb.ask("hi")


# ─── astream() ───────────────────────────────────────────────────


class TestChatBaseAstream:
    def test_astream_with_streaming_llm(self) -> None:
        stub = StubStreamingLLM(chunks=["a", "b", "c"])
        cb = ChatBase(llm_client=stub, system_prompt="S")
        chunks = []
        # Use asyncio.run to drive the async generator.
        async def collect() -> None:
            async for c in cb.astream("hi"):
                chunks.append(c)
        asyncio.run(collect())
        assert chunks == ["a", "b", "c"]

    def test_astream_falls_back_to_chat_for_non_streaming_llm(self) -> None:
        """If the LLM client doesn't expose ``astream_chat``, yield the full reply."""

        class PlainStub:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, messages, **kw):
                self.calls += 1
                return "single-chunk"

        stub = PlainStub()
        cb = ChatBase(llm_client=stub)
        chunks: list[str] = []
        async def collect() -> None:
            async for c in cb.astream("hi"):
                chunks.append(c)
        asyncio.run(collect())
        assert chunks == ["single-chunk"]

    def test_astream_appends_user_and_assistant(self) -> None:
        stub = StubStreamingLLM(chunks=["x", "y"])
        cb = ChatBase(llm_client=stub, system_prompt="S")
        s = cb.new_session()
        async def collect() -> None:
            async for _ in cb.astream("hi", session=s):
                pass
        asyncio.run(collect())
        assert [m.role for m in s.messages] == ["system", "user", "assistant"]
        assert s.messages[2].content == "xy"
