"""Unit tests for ChatService — SSE chat service.

Covers:

  - ChatEvent factory (7 event types)
  - AgentContext (per-session state)
  - ChatService init + DB persistence
  - SSE chat flow (session creation, message persistence)
  - Wiki prefix parsing (@wiki_id)
  - Message truncation
  - System prompt construction
  - Tool spec generation
  - approve_confirmation_continue flow
  - WikiService integration

Target: 20+ tests, no real LLM calls.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.service import (
    AgentContext,
    ChatEvent,
    ChatService,
    _parse_perl_args,
    _parse_text_tool_call,
)


def _run_async(coro: Any) -> Any:
    """Run async coroutine."""
    return asyncio.run(coro)


# ─── Mock WikiService ─────────────────────────────────────────────


class MockWikiService:
    """Mock WikiService for ChatService tests."""

    def __init__(self) -> None:
        self.llm = MagicMock()
        self.llm.astream_chat = MagicMock()
        self.default_wiki_id = "test_wiki"
        self.wiki = MagicMock(name="Wiki")
        self.tool_registry = MagicMock()
        self.tool_registry.list_tools = MagicMock(return_value=[])
        # execute is async, so use AsyncMock
        self.tool_registry.execute = AsyncMock(
            return_value={"result": "ok"}
        )
        # ChatService calls wiki_service.approve_confirmation
        self.approve_confirmation = AsyncMock(
            return_value={"status": "ok", "result": "done"}
        )
        # Keep confirm_execution for backward compat
        self.confirm_execution = self.approve_confirmation

    def get_default_wiki_id(self) -> str:
        return self.default_wiki_id

    def get_wiki(self, wiki_id: str | None = None) -> Any:
        return self.wiki

    def get_llm(self) -> Any:
        return self.llm

    def reload_llm(self) -> None:
        self.llm = MagicMock()

    def get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.tool_registry


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def data_dir() -> Path:
    d = Path(tempfile.mkdtemp())
    yield d


@pytest.fixture
def wiki_service_mock() -> MockWikiService:
    return MockWikiService()


@pytest.fixture
def chat_service(
    wiki_service_mock: MockWikiService, data_dir: Path
) -> ChatService:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ChatService(wiki_service_mock, data_dir)


# ─── ChatEvent factory ───────────────────────────────────────────


class TestChatEvent:
    def test_message_delta(self) -> None:
        e = ChatEvent.message_delta("hello")
        assert e["type"] == "message_delta"
        assert e["content"] == "hello"

    def test_thinking(self) -> None:
        e = ChatEvent.thinking("reasoning...")
        assert e["type"] == "thinking"
        assert e["content"] == "reasoning..."

    def test_tool_call_start(self) -> None:
        e = ChatEvent.tool_call_start("search", {"q": "x"})
        assert e["type"] == "tool_call_start"
        assert e["tool"] == "search"
        assert e["args"] == {"q": "x"}

    def test_tool_call_end(self) -> None:
        e = ChatEvent.tool_call_end("search", {"hits": []})
        assert e["type"] == "tool_call_end"
        assert e["tool"] == "search"

    def test_confirmation_required(self) -> None:
        e = ChatEvent.confirmation_required(
            "conf-1", "wiki_write_page",
            {"page": "Foo"}, {"impact": "high"},
        )
        assert e["type"] == "confirmation_required"
        assert e["confirmation_id"] == "conf-1"
        assert e["tool"] == "wiki_write_page"
        assert e["args"] == {"page": "Foo"}
        assert e["impact"] == {"impact": "high"}

    def test_done(self) -> None:
        e = ChatEvent.done("Final answer")
        assert e["type"] == "done"
        assert e["final_response"] == "Final answer"

    def test_error(self) -> None:
        e = ChatEvent.error("Something went wrong")
        assert e["type"] == "error"
        assert e["message"] == "Something went wrong"


# ─── AgentContext ────────────────────────────────────────────────


class TestAgentContext:
    def test_init_empty(self) -> None:
        ctx = AgentContext()
        assert ctx.wiki_id is None
        assert ctx.messages == []
        assert ctx.recent_wiki_id is None
        assert ctx._tool_calls == {}

    def test_add_user_message(self) -> None:
        ctx = AgentContext()
        ctx.add_user_message("hello")
        assert ctx.messages == [{"role": "user", "content": "hello"}]

    def test_add_assistant_message(self) -> None:
        ctx = AgentContext()
        ctx.add_assistant_message("hi")
        assert ctx.messages == [{"role": "assistant", "content": "hi"}]

    def test_get_messages_returns_copy(self) -> None:
        ctx = AgentContext()
        ctx.add_user_message("a")
        msgs = ctx.get_messages()
        msgs.append({"role": "user", "content": "b"})
        # Original should be unchanged
        assert len(ctx.messages) == 1

    def test_set_recent_wiki(self) -> None:
        ctx = AgentContext()
        ctx.set_recent_wiki("my_wiki")
        assert ctx.recent_wiki_id == "my_wiki"


# ─── ChatService init ────────────────────────────────────────────


class TestChatServiceInit:
    def test_init(self, chat_service: ChatService) -> None:
        assert chat_service.wiki_service is not None
        assert chat_service.db is not None
        assert chat_service._contexts == {}

    def test_db_creates_tables(
        self, chat_service: ChatService
    ) -> None:
        stats = chat_service.db.get_db_stats()
        assert "autoresearch_sessions" in stats["tables"]
        assert "chat_sessions" in stats["tables"]


# ─── Private helpers ─────────────────────────────────────────────


class TestChatServiceHelpers:
    def test_parse_wiki_prefix_match(
        self, chat_service: ChatService
    ) -> None:
        wiki_id, msg = chat_service._parse_wiki_prefix(
            "@my_wiki hello world"
        )
        assert wiki_id == "my_wiki"
        assert msg == "hello world"

    def test_parse_wiki_prefix_no_match(
        self, chat_service: ChatService
    ) -> None:
        wiki_id, msg = chat_service._parse_wiki_prefix("hello world")
        assert wiki_id is None
        assert msg == "hello world"

    def test_build_system_prompt_no_wiki(
        self, chat_service: ChatService
    ) -> None:
        # Phase 3.1 (v0.36): _build_system_prompt is now async.
        prompt = asyncio.run(chat_service._build_system_prompt())
        assert "wiki assistant" in prompt

    def test_build_system_prompt_with_wiki(
        self, chat_service: ChatService
    ) -> None:
        # Phase 3.1 (v0.36): _build_system_prompt is now async.
        prompt = asyncio.run(chat_service._build_system_prompt("my_wiki"))
        assert "my_wiki" in prompt

    def test_truncate_messages_short(
        self, chat_service: ChatService
    ) -> None:
        msgs = [{"role": "system", "content": "sys"}]
        result = chat_service._truncate_messages(msgs, max_messages=50)
        assert result == msgs

    def test_truncate_messages_long(
        self, chat_service: ChatService
    ) -> None:
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(60):
            msgs.append({"role": "user", "content": f"msg{i}"})
        result = chat_service._truncate_messages(msgs, max_messages=10)
        assert len(result) == 12  # system + summary + 10

    def test_get_toolspec_empty(
        self, chat_service: ChatService
    ) -> None:
        # Mock tool_registry returns empty list
        chat_service.wiki_service.tool_registry.list_tools.return_value = []
        specs = chat_service._get_toolspec(
            chat_service.wiki_service.tool_registry
        )
        assert specs == []

    def test_get_toolspec_with_tools(
        self, chat_service: ChatService
    ) -> None:
        chat_service.wiki_service.tool_registry.list_tools.return_value = [
            {
                "name": "search",
                "description": "Search wiki",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            }
        ]
        specs = chat_service._get_toolspec(
            chat_service.wiki_service.tool_registry
        )
        assert len(specs) == 1
        assert specs[0]["function"]["name"] == "search"

    def test_get_wiki_for_context_with_id(
        self, chat_service: ChatService
    ) -> None:
        ctx = AgentContext(wiki_id="test_wiki")
        wiki = chat_service._get_wiki_for_context(ctx)
        assert wiki is not None

    def test_get_wiki_for_context_recent(
        self, chat_service: ChatService
    ) -> None:
        ctx = AgentContext()
        ctx.set_recent_wiki("test_wiki")
        wiki = chat_service._get_wiki_for_context(ctx)
        assert wiki is not None

    def test_get_wiki_for_context_no_id(
        self, chat_service: ChatService
    ) -> None:
        ctx = AgentContext()
        wiki = chat_service._get_wiki_for_context(ctx)
        # Should fall back to default wiki
        assert wiki is not None

    def test_save_message(
        self, chat_service: ChatService
    ) -> None:
        chat_service._save_message("s1", "user", "hello")
        msgs = chat_service.db.get_chat_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"


# ─── SSE chat flow ───────────────────────────────────────────────


class TestSSEChatFlow:
    @pytest.mark.asyncio
    async def test_chat_new_session(
        self, chat_service: ChatService
    ) -> None:
        # Mock LLM to return a simple "done" event
        async def fake_stream(messages, tools=None):
            yield {"type": "done", "content": "Hello!"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="hi"):
            events.append(event)

        # Should have session_created and done events
        assert any(e.get("type") == "session_created" for e in events)
        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_chat_existing_session(
        self, chat_service: ChatService
    ) -> None:
        # Create a session first
        sid = chat_service.db.create_chat_session()

        async def fake_stream(messages, tools=None):
            yield {"type": "done", "content": "Reply!"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(
            message="hi", session_id=sid
        ):
            events.append(event)

        # Should NOT have session_created (session already exists)
        assert not any(
            e.get("type") == "session_created" for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_chat_wiki_prefix(
        self, chat_service: ChatService
    ) -> None:
        async def fake_stream(messages, tools=None):
            yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(
            message="@other_wiki hello"
        ):
            events.append(event)

        # Check that the session was created with the right wiki_id
        session_created = next(
            e for e in events
            if e.get("type") == "session_created"
        )
        sid = session_created["session_id"]
        session = chat_service.db.get_chat_session(sid)
        assert session["wiki_id"] == "other_wiki"

    @pytest.mark.asyncio
    async def test_chat_message_persisted(
        self, chat_service: ChatService
    ) -> None:
        async def fake_stream(messages, tools=None):
            yield {"type": "done", "content": "reply"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="user question"):
            events.append(event)

        sid = next(
            e["session_id"] for e in events
            if e.get("type") == "session_created"
        )
        msgs = chat_service.db.get_chat_messages(sid)
        # user + assistant (DESC order, so msgs[0] is assistant)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "assistant"
        assert msgs[1]["role"] == "user"
        assert msgs[0]["content"] == "reply"
        assert msgs[1]["content"] == "user question"

    @pytest.mark.asyncio
    async def test_chat_thinking_event(
        self, chat_service: ChatService
    ) -> None:
        async def fake_stream(messages, tools=None):
            yield {"type": "thinking", "text": "Let me think..."}
            yield {"type": "done", "content": "result"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="hi"):
            events.append(event)

        assert any(e.get("type") == "thinking" for e in events)

    @pytest.mark.asyncio
    async def test_chat_tool_call_event(
        self, chat_service: ChatService
    ) -> None:
        async def fake_stream(messages, tools=None):
            yield {
                "type": "tool_call",
                "tool": "wiki_search",
                "args": '{"q": "test"}',
            }
            yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="search"):
            events.append(event)

        assert any(
            e.get("type") == "tool_call_start" for e in events
        )
        assert any(
            e.get("type") == "tool_call_end" for e in events
        )

    @pytest.mark.asyncio
    async def test_chat_confirmation_required(
        self, chat_service: ChatService
    ) -> None:
        # Mock tool_registry to return confirmation_required
        # Use AsyncMock since the code awaits execute()
        chat_service.wiki_service.tool_registry.execute = AsyncMock(
            return_value={
                "status": "confirmation_required",
                "confirmation_id": "conf-1",
                "impact": {"risk": "high"},
            }
        )

        async def fake_stream(messages, tools=None):
            yield {
                "type": "tool_call",
                "tool": "wiki_write_page",
                "args": "{}",
            }
            yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="write"):
            events.append(event)

        assert any(
            e.get("type") == "confirmation_required" for e in events
        )

    @pytest.mark.asyncio
    async def test_chat_error_event(
        self, chat_service: ChatService
    ) -> None:
        async def fake_stream(messages, tools=None):
            raise RuntimeError("LLM down")
            yield  # never reached, but needed for async gen

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.chat(message="hi"):
            events.append(event)

        assert any(e.get("type") == "error" for e in events)


# ─── Text-mode tool-call parsing ────────────────────────────────


class TestParseTextToolCall:
    def test_basic_user_example(self) -> None:
        # The exact example from the bug report.
        body = (
            '{tool => "wiki_read_page", '
            'args => { --page_name "overview" }}'
        )
        parsed = _parse_text_tool_call(body)
        assert parsed is not None
        name, args = parsed
        assert name == "wiki_read_page"
        assert args == {"page_name": "overview"}

    def test_quoted_key_value(self) -> None:
        body = (
            '{tool => "search", '
            'args => { "q" => "hello world" }}'
        )
        parsed = _parse_text_tool_call(body)
        assert parsed is not None
        name, args = parsed
        assert name == "search"
        assert args == {"q": "hello world"}

    def test_mixed_keyword_and_arrow(self) -> None:
        body = (
            '{tool => "x", '
            'args => { --a 1, --b "two words", --c three }}'
        )
        parsed = _parse_text_tool_call(body)
        assert parsed is not None
        _, args = parsed
        assert args == {"a": "1", "b": "two words", "c": "three"}

    def test_no_args_block(self) -> None:
        parsed = _parse_text_tool_call('{tool => "ping"}')
        assert parsed is not None
        name, args = parsed
        assert name == "ping"
        assert args == {}

    def test_unparseable_returns_none(self) -> None:
        assert _parse_text_tool_call("not a tool call") is None
        assert _parse_text_tool_call("") is None
        assert _parse_text_tool_call('{no_tool_key => "x"}') is None

    def test_nested_braces(self) -> None:
        body = (
            '{tool => "x", '
            'args => { --config { --a 1 } }}'
        )
        parsed = _parse_text_tool_call(body)
        assert parsed is not None
        _, args = parsed
        assert args["config"] == "{ --a 1 }"

    def test_perl_args_basic(self) -> None:
        assert _parse_perl_args('{ --a 1, --b "two"}') == {
            "a": "1", "b": "two",
        }


class TestTextModeToolCallDispatch:
    @pytest.mark.asyncio
    async def test_text_mode_tool_call_executes(
        self, chat_service: ChatService
    ) -> None:
        # LLM streams content that contains a text-mode tool call
        # followed by a done event. The tool should run, and the
        # [TOOL_CALL] markup should not appear in message_delta.
        # (Phase 1.1 / v0.36: tool results are now fed back to
        # the LLM in a follow-up call, so we yield an empty
        # content stream on the second call to terminate cleanly.)
        call_count = {"n": 0}

        async def fake_stream(messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield {
                    "type": "content",
                    "text": (
                        'Let me check that page. '
                        '[TOOL_CALL] {tool => "wiki_read_page", '
                        'args => { --page_name "overview" }} [/TOOL_CALL] '
                        'Done.'
                    ),
                }
                yield {"type": "done", "content": "Done."}
            else:
                # Second (final) call: just a plain done.
                yield {"type": "done", "content": "Done."}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events: list[dict] = []
        async for event in chat_service.chat(message="read overview"):
            events.append(event)

        # Tool call should have been dispatched exactly once.
        starts = [e for e in events if e.get("type") == "tool_call_start"]
        ends = [e for e in events if e.get("type") == "tool_call_end"]
        assert len(starts) == 1
        assert starts[0]["tool"] == "wiki_read_page"
        assert starts[0]["args"] == {"page_name": "overview"}
        assert len(ends) == 1

        # Tool registry should have been called with the right args.
        chat_service.wiki_service.tool_registry.execute.assert_awaited_once_with(
            "wiki_read_page", {"page_name": "overview"},
        )

        # The [TOOL_CALL] markup must NOT appear in any message_delta.
        deltas = [e["content"] for e in events if e.get("type") == "message_delta"]
        joined = "".join(deltas)
        assert "[TOOL_CALL]" not in joined
        assert "[/TOOL_CALL]" not in joined
        # But the surrounding text should still flow.
        assert "Let me check that page." in joined
        assert "Done." in joined

    @pytest.mark.asyncio
    async def test_text_mode_split_across_chunks(
        self, chat_service: ChatService
    ) -> None:
        # The text-mode block is split across multiple content chunks.
        call_count = {"n": 0}

        async def fake_stream(messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield {"type": "content", "text": "Intro [TOOL_CALL] "}
                yield {
                    "type": "content",
                    "text": '{tool => "wiki_read_page", args => { --page_name "x" }}',
                }
                yield {"type": "content", "text": " [/TOOL_CALL] tail"}
                yield {"type": "done", "content": "ok"}
            else:
                yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events: list[dict] = []
        async for event in chat_service.chat(message="hi"):
            events.append(event)

        assert any(
            e.get("type") == "tool_call_start" for e in events
        )
        deltas = [
            e["content"] for e in events
            if e.get("type") == "message_delta"
        ]
        joined = "".join(deltas)
        assert "[TOOL_CALL]" not in joined
        assert "Intro" in joined
        assert "tail" in joined

    @pytest.mark.asyncio
    async def test_text_mode_unparseable_passes_through(
        self, chat_service: ChatService
    ) -> None:
        # A malformed block shouldn't crash; it falls through to the
        # user as text and no tool is invoked.
        call_count = {"n": 0}

        async def fake_stream(messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield {
                    "type": "content",
                    "text": "[TOOL_CALL] garbage no tool key [/TOOL_CALL]",
                }
                yield {"type": "done", "content": "ok"}
            else:
                yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events: list[dict] = []
        async for event in chat_service.chat(message="hi"):
            events.append(event)

        chat_service.wiki_service.tool_registry.execute.assert_not_awaited()
        deltas = [
            e["content"] for e in events
            if e.get("type") == "message_delta"
        ]
        joined = "".join(deltas)
        assert "[TOOL_CALL]" in joined

    @pytest.mark.asyncio
    async def test_native_tool_call_still_works(
        self, chat_service: ChatService
    ) -> None:
        # Regression check: the refactor must not break the native
        # tool_call event path.
        async def fake_stream(messages, tools=None):
            yield {
                "type": "tool_call",
                "tool": "wiki_search",
                "args": '{"q": "test"}',
            }
            yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events: list[dict] = []
        async for event in chat_service.chat(message="search"):
            events.append(event)

        assert any(
            e.get("type") == "tool_call_start" for e in events
        )
        assert any(
            e.get("type") == "tool_call_end" for e in events
        )


# ─── Context management ──────────────────────────────────────────


class TestContextManagement:
    def test_get_or_create_context_new(
        self, chat_service: ChatService
    ) -> None:
        # Phase 3.2 (v0.36): _get_or_create_context is now async.
        ctx = asyncio.run(chat_service._get_or_create_context("new-session"))
        assert isinstance(ctx, AgentContext)
        assert ctx.wiki_id is None

    def test_get_or_create_context_existing(
        self, chat_service: ChatService
    ) -> None:
        ctx1 = asyncio.run(chat_service._get_or_create_context("s1"))
        ctx2 = asyncio.run(chat_service._get_or_create_context("s1"))
        assert ctx1 is ctx2

    def test_get_or_create_context_restores_messages(
        self, chat_service: ChatService
    ) -> None:
        # Create session + save messages
        sid = chat_service.db.create_chat_session()
        chat_service.db.save_chat_message({
            "session_id": sid, "role": "user", "content": "hi"
        })
        chat_service.db.save_chat_message({
            "session_id": sid, "role": "assistant", "content": "hello"
        })

        ctx = asyncio.run(chat_service._get_or_create_context(sid))
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "hi"
        assert ctx.messages[1]["content"] == "hello"

    def test_get_or_create_context_restores_wiki_id(
        self, chat_service: ChatService
    ) -> None:
        sid = chat_service.db.create_chat_session(wiki_id="test_wiki")
        ctx = asyncio.run(chat_service._get_or_create_context(sid))
        assert ctx.recent_wiki_id == "test_wiki"


# ─── Confirmation continue flow ─────────────────────────────────


class TestConfirmationContinue:
    @pytest.mark.asyncio
    async def test_approve_confirmation_continue_success(
        self, chat_service: ChatService
    ) -> None:
        sid = chat_service.db.create_chat_session(wiki_id="test_wiki")

        async def fake_stream(messages, tools=None):
            yield {"type": "done", "content": "ok"}

        chat_service.wiki_service.llm.astream_chat = fake_stream

        events = []
        async for event in chat_service.approve_confirmation_continue(
            confirmation_id="conf-1", session_id=sid
        ):
            events.append(event)

        assert any(
            e.get("type") == "tool_call_end" for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_approve_confirmation_continue_error(
        self, chat_service: ChatService
    ) -> None:
        sid = chat_service.db.create_chat_session()
        # ChatService calls wiki_service.approve_confirmation
        chat_service.wiki_service.approve_confirmation = AsyncMock(
            return_value={"status": "error", "error": "rejected"}
        )

        events = []
        async for event in chat_service.approve_confirmation_continue(
            confirmation_id="bad", session_id=sid
        ):
            events.append(event)

        assert any(e.get("type") == "error" for e in events)

    @pytest.mark.asyncio
    async def test_approve_confirmation_continue_no_wiki(
        self, chat_service: ChatService
    ) -> None:
        sid = chat_service.db.create_chat_session()
        chat_service.wiki_service.default_wiki_id = None

        events = []
        async for event in chat_service.approve_confirmation_continue(
            confirmation_id="conf-1", session_id=sid
        ):
            events.append(event)

        assert any(e.get("type") == "error" for e in events)


# ─── Phase 1.1 — Iterative tool-call loop (v0.36) ──────────────────


class TestChatLoopIteration:
    """Phase 1.1 (v0.36): tool results must be fed back to the LLM
    in subsequent iterations, breaking the single-pass pattern that
    silently dropped tool outputs."""

    @staticmethod
    async def _stream_from(events: list[dict]) -> Any:
        for e in events:
            yield e

    @pytest.mark.asyncio
    async def test_loop_emits_done_after_single_pass_no_tools(
        self, chat_service: ChatService
    ) -> None:
        """Plain chat (no tools) returns a single done event."""
        sid = chat_service.db.create_chat_session()
        chat_service.wiki_service.llm.astream_chat = MagicMock(
            return_value=TestChatLoopIteration._stream_from([
                {"type": "content", "text": "Hello back"},
                {"type": "done", "content": "Hello back"},
            ])
        )

        events = []
        async for ev in chat_service.chat("hi", session_id=sid):
            events.append(ev)

        assert any(e["type"] == "done" for e in events)
        # Only ONE done event (no extra from the loop).
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_loop_iterates_when_llm_emits_tool_call(
        self, chat_service: ChatService
    ) -> None:
        """When the LLM emits a tool_call, the loop calls the LLM
        a SECOND time so it can use the tool result in its final
        answer."""
        sid = chat_service.db.create_chat_session()
        # First LLM call: emits a tool_call + done-without-content.
        # Second LLM call: emits the final answer using the tool
        # result.
        call_count = {"n": 0}

        async def fake_stream(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield {"type": "content", "text": "Let me check."}
                yield {
                    "type": "tool_call",
                    "tool": "wiki_search",
                    "args": '{"q": "test"}',
                }
                yield {"type": "done", "content": "Let me check."}
            else:
                yield {
                    "type": "content",
                    "text": "Found it.",
                }
                yield {
                    "type": "done",
                    "content": "Found it.",
                }

        chat_service.wiki_service.llm.astream_chat = fake_stream
        chat_service.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"result": ["hit1", "hit2"]}
        )

        events = []
        async for ev in chat_service.chat("find test", session_id=sid):
            events.append(ev)

        # LLM was called twice (1st for tool, 2nd for final).
        assert call_count["n"] == 2
        # Tool was executed once.
        assert chat_service.wiki_service.tool_registry.execute.await_count == 1
        # Final answer is the second LLM's content.
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["final_response"] == "Found it."

    @pytest.mark.asyncio
    async def test_loop_stops_on_confirmation_required(
        self, chat_service: ChatService
    ) -> None:
        """Confirmation-required tools halt the loop after the
        first iteration (frontend will resume via
        approve_confirmation_continue)."""
        sid = chat_service.db.create_chat_session()
        call_count = {"n": 0}

        async def fake_stream(*args, **kwargs):
            call_count["n"] += 1
            yield {"type": "tool_call", "tool": "wiki_write_page", "args": "{}"}
            yield {"type": "done", "content": ""}

        chat_service.wiki_service.llm.astream_chat = fake_stream
        chat_service.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"status": "confirmation_required", "confirmation_id": "c-1"}
        )

        events = []
        async for ev in chat_service.chat("write", session_id=sid):
            events.append(ev)

        # LLM called once only — confirmation pauses the loop.
        assert call_count["n"] == 1
        assert any(e["type"] == "confirmation_required" for e in events)

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations(
        self, chat_service: ChatService
    ) -> None:
        """Infinite-tool loop is bounded by max_iterations."""
        sid = chat_service.db.create_chat_session()
        call_count = {"n": 0}

        async def infinite_tools(*args, **kwargs):
            call_count["n"] += 1
            yield {
                "type": "tool_call",
                "tool": "wiki_search",
                "args": '{"q": "x"}',
            }
            yield {"type": "done", "content": ""}

        chat_service.wiki_service.llm.astream_chat = infinite_tools
        chat_service.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"result": []}
        )
        chat_service.DEFAULT_MAX_CHAT_ITERATIONS = 3

        events = []
        async for ev in chat_service.chat("loop", session_id=sid):
            events.append(ev)

        # Capped at max_iterations.
        assert call_count["n"] == 3
        # Final fallback done emitted.
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1


# ─── Phase 1.2 — save_message error visibility (v0.36) ──────────────


class TestSaveMessageErrors:
    """Phase 1.2 (v0.36): DB save failures are logged + counted,
    not silently swallowed."""

    def test_save_error_count_increments_on_failure(
        self, chat_service: ChatService
    ) -> None:
        """Forced DB error increments the counter."""
        sid = chat_service.db.create_chat_session()
        # Make save_chat_message raise
        original = chat_service.db.save_chat_message
        chat_service.db.save_chat_message = MagicMock(
            side_effect=RuntimeError("disk full")
        )

        chat_service._save_message(sid, "user", "hello")
        chat_service._save_message(sid, "user", "world")

        assert chat_service._save_error_count == 2
        # Restore
        chat_service.db.save_chat_message = original

    def test_save_warning_event_factory(self) -> None:
        e = ChatEvent.save_warning("persistence failed")
        assert e["type"] == "save_warning"
        assert "persistence failed" in e["message"]


# ─── Phase 1.3 — UUID length + INSERT OR IGNORE (v0.36) ───────────


class TestMessageId:
    """Phase 1.3 (v0.36): full 32-hex uuid; INSERT OR IGNORE."""

    def test_save_message_uses_full_uuid(
        self, chat_service: ChatService
    ) -> None:
        """Generated message ids are 32 hex chars (was 8)."""
        sid = chat_service.db.create_chat_session()
        chat_service._save_message(sid, "user", "hi")
        msgs = chat_service.db.get_chat_messages(sid)
        assert len(msgs) == 1
        msg_id = msgs[0].get("id", "")
        # 32 hex chars (full uuid4().hex) — not the old 8.
        assert len(msg_id) == 32
        int(msg_id, 16)  # valid hex

    def test_save_message_ignores_duplicates(
        self, chat_service: ChatService
    ) -> None:
        """INSERT OR IGNORE prevents overwrites on id collision."""
        sid = chat_service.db.create_chat_session()
        chat_service.db.save_chat_message({
            "id": "duplicate-id",
            "session_id": sid,
            "role": "user",
            "content": "first",
            "tool_calls": None,
        })
        chat_service.db.save_chat_message({
            "id": "duplicate-id",
            "session_id": sid,
            "role": "user",
            "content": "second",
            "tool_calls": None,
        })
        msgs = chat_service.db.get_chat_messages(sid)
        # The first message survives; the second is dropped.
        assert any(m.get("content") == "first" for m in msgs)
        assert not any(m.get("content") == "second" for m in msgs)


# ─── Phase 1.5 — Shared ChatDatabase instance (v0.36) ────────────


class TestSharedChatDatabase:
    """Phase 1.5 (v0.36): ChatService accepts an injected
    ChatDatabase to avoid duplicate connections on the same file."""

    def test_chat_service_uses_injected_db(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        shared_db = ChatDatabase(data_dir)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            svc = ChatService(wiki_service_mock, data_dir, chat_db=shared_db)
        assert svc.db is shared_db

    def test_chat_service_creates_db_when_not_provided(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            svc = ChatService(wiki_service_mock, data_dir)
        assert svc.db is not None
        assert isinstance(svc.db.db_path, Path)


# ─── Phase 3 — MemoryManager integration (v0.36) ──────────────────


class TestMemoryManagerIntegration:
    """Phase 3 (v0.36): MemoryManager is wired into ChatService
    for system prompt injection, history restore, tool result
    persistence, and related-history search."""

    @staticmethod
    def _make_svc_with_memory(
        wiki_service_mock: MockWikiService,
        data_dir: Path,
    ):
        from llmwikify.apps.db import AppDatabase
        from llmwikify.apps.chat.memory import MemoryManager

        app_db = AppDatabase(data_dir)
        mm = MemoryManager(app_db, wiki=None, data_dir=data_dir)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            svc = ChatService(
                wiki_service_mock,
                data_dir,
                chat_db=app_db.chat,
                memory_manager=mm,
            )
        return svc, mm, app_db

    def test_memory_manager_injected(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, mm, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        assert svc.memory_manager is mm

    def test_system_prompt_includes_date(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, _, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        prompt = asyncio.run(svc._build_system_prompt())
        assert "Today's date" in prompt
        assert "2026" in prompt

    def test_system_prompt_includes_wiki_context(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, _, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        prompt = asyncio.run(svc._build_system_prompt("my_wiki"))
        assert "my_wiki" in prompt

    def test_system_prompt_includes_preferences(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, mm, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        # Set a preference
        mm.preferences.set("default", "style", "verbose")
        prompt = asyncio.run(svc._build_system_prompt())
        assert "User preferences" in prompt
        assert "style" in prompt
        assert "verbose" in prompt

    def test_tool_result_persisted_to_context(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, mm, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        sid = svc.db.create_chat_session()

        async def run():
            await svc._persist_tool_result(
                sid, "wiki_read_page",
                {"page_name": "overview"},
                {"result": "page content here"},
            )
        asyncio.run(run())

        # Verify persisted
        entries = asyncio.run(mm.context.alist(sid))
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "tool_result"
        assert "wiki_read_page" in entries[0]["content"]

    def test_history_loaded_through_memory_manager(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        svc, mm, _ = self._make_svc_with_memory(wiki_service_mock, data_dir)
        sid = svc.db.create_chat_session()
        # Add history through the memory manager
        asyncio.run(mm.conversation.aadd(sid, "user", "what is wiki?"))
        asyncio.run(mm.conversation.aadd(sid, "assistant", "A wiki is..."))

        ctx = asyncio.run(svc._get_or_create_context(sid))
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "what is wiki?"
        assert ctx.messages[1]["content"] == "A wiki is..."


# ─── Phase 4 — Reliability (v0.36) ─────────────────────────────────


class TestRetryManagers:
    """Phase 4.1-4.2 (v0.36): verify retry managers work."""

    def test_llm_retry_manager_retries_transient(self):
        from llmwikify.apps.chat.retry_managers import LLMRetryManager
        mgr = LLMRetryManager(max_attempts=3, base_delay=0.01)
        call_count = {"n": 0}

        async def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("rate limit exceeded")
            return "ok"

        result = asyncio.run(mgr.call(flaky))
        assert result == "ok"
        assert call_count["n"] == 3

    def test_llm_retry_manager_fails_fast_on_validation(self):
        from llmwikify.apps.chat.retry_managers import LLMRetryManager
        mgr = LLMRetryManager(max_attempts=3, base_delay=0.01)

        async def bad_json():
            raise ValueError("invalid JSON decode")

        with pytest.raises(ValueError, match="invalid JSON"):
            asyncio.run(mgr.call(bad_json))

    def test_db_retry_manager_retries_locked(self):
        from llmwikify.apps.chat.retry_managers import DBRetryManager
        mgr = DBRetryManager(max_attempts=3, base_delay=0.01)
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        result = mgr.call(flaky)
        assert result == "ok"
        assert call_count["n"] == 3

    def test_save_message_uses_db_retry(
        self, wiki_service_mock: MockWikiService, data_dir: Path
    ) -> None:
        """_save_message should use DBRetryManager."""
        from llmwikify.apps.chat.db import ChatDatabase
        shared_db = ChatDatabase(data_dir)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            svc = ChatService(
                wiki_service_mock, data_dir, chat_db=shared_db,
            )
        # Should not raise
        svc._save_message("session-1", "user", "hello")
        msgs = svc.db.get_chat_messages("session-1")
        assert len(msgs) == 1


# ─── ReActEngine path (v0.37) ────────────────────────────────────


class _ReactMockWikiService:
    """Local MockWikiService for ReAct path tests."""

    def __init__(
        self,
        llm_events: list[dict] | None = None,
        tool_result: Any = None,
    ) -> None:
        self.llm = MagicMock()
        self.llm_events = llm_events or []
        events = self.llm_events

        async def _astream(messages, tools=None):
            for ev in events:
                yield ev
        self.llm.astream_chat = _astream
        self.default_wiki_id = "test_wiki"
        self.wiki = MagicMock(name="Wiki")
        self.tool_registry = MagicMock()
        self.tool_registry.list_tools = MagicMock(return_value=[
            {
                "name": "search",
                "description": "Search",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "write",
                "description": "Write",
                "parameters": {"type": "object", "properties": {}},
            },
        ])
        self.tool_registry.execute = AsyncMock(
            return_value=tool_result or {"result": "ok"},
        )
        self.approve_confirmation = AsyncMock(
            return_value={"status": "ok", "result": "done"},
        )

    def get_default_wiki_id(self) -> str:
        return self.default_wiki_id

    def get_wiki(self, wiki_id: str | None = None) -> Any:
        return self.wiki

    def get_llm(self) -> Any:
        return self.llm

    def get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.tool_registry


class TestReActEnginePath:
    """Tests for the dual-track chat(): use_react_engine=True path.

    Verifies the ReAct path produces the same SSE event vocabulary
    as the aask_with_tools path.
    """

    def _make_react_chat(
        self, data_dir: Path, llm_events: list[dict],
        tool_result: Any = None,
    ) -> ChatService:
        wiki = _ReactMockWikiService(
            llm_events=llm_events, tool_result=tool_result,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return ChatService(wiki, data_dir, use_react_engine=True)

    @pytest.mark.asyncio
    async def test_react_default_enabled(self, data_dir: Path) -> None:
        wiki = _ReactMockWikiService()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            svc = ChatService(wiki, data_dir)
        assert svc.use_react_engine is True

    @pytest.mark.asyncio
    async def test_react_path_yields_done_for_final_answer(
        self, data_dir: Path,
    ) -> None:
        events = [
            {"type": "content", "text": "Hello! "},
            {"type": "content", "text": "How can I help?"},
            {"type": "done", "content": "Hello! How can I help?"},
        ]
        chat = self._make_react_chat(data_dir, events)
        out: list[dict] = []
        async for ev in chat.chat(message="hi", session_id="s1"):
            out.append(ev)

        # Should have session_created, content events, and done
        types = [e.get("type") for e in out]
        assert "session_created" in types
        assert "done" in types
        # Final response should be set
        done_event = next(e for e in out if e.get("type") == "done")
        assert done_event["final_response"] == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_react_path_yields_tool_events(
        self, data_dir: Path,
    ) -> None:
        first = [
            {"type": "content", "text": "Searching. "},
            {
                "type": "tool_call",
                "tool": "search",
                "args": json.dumps({"q": "x"}),
            },
            {"type": "done", "content": ""},
        ]
        second = [
            {"type": "content", "text": "Found."},
            {"type": "done", "content": ""},
        ]

        # Use call-counting LLM
        call_count = {"n": 0}

        async def _astream(messages, tools=None):
            idx = call_count["n"]
            response = [first, second][idx] if idx < 2 else [
                {"type": "done", "content": ""}
            ]
            call_count["n"] += 1
            for ev in response:
                yield ev

        wiki = _ReactMockWikiService(llm_events=[], tool_result={"result": "ok"})
        wiki.llm.astream_chat = _astream
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)

        out: list[dict] = []
        async for ev in chat.chat(message="search", session_id="s1"):
            out.append(ev)

        types = [e.get("type") for e in out]
        # Should have tool_call_start and tool_call_end
        assert types.count("tool_call_start") >= 1
        assert types.count("tool_call_end") >= 1
        # Should have done at the end
        assert types[-1] == "done"
        # Tool was executed
        wiki.tool_registry.execute.assert_called_with(
            "search", {"q": "x"},
        )

    @pytest.mark.asyncio
    async def test_react_path_handles_confirmation(
        self, data_dir: Path,
    ) -> None:
        events = [
            {"type": "content", "text": "Writing. "},
            {
                "type": "tool_call",
                "tool": "write",
                "args": json.dumps({"content": "x"}),
            },
            {"type": "done", "content": ""},
        ]
        confirmation_result = {
            "status": "confirmation_required",
            "confirmation_id": "conf-1",
            "impact": {"desc": "writing"},
        }
        wiki = _ReactMockWikiService(
            llm_events=events, tool_result=confirmation_result,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)

        out: list[dict] = []
        async for ev in chat.chat(message="write", session_id="s1"):
            out.append(ev)

        types = [e.get("type") for e in out]
        conf_events = [e for e in out if e.get("type") == "confirmation_required"]
        assert len(conf_events) == 1
        assert conf_events[0]["confirmation_id"] == "conf-1"

    @pytest.mark.asyncio
    async def test_react_path_multi_round(
        self, data_dir: Path,
    ) -> None:
        """Three-round ReAct: tool → tool → final answer.

        Verifies that after a tool call the LLM is invoked again
        (not just terminated) and can dispatch a follow-up tool
        before producing the final answer.
        """
        r1 = [
            {"type": "content", "text": "Searching. "},
            {"type": "tool_call", "tool": "search",
             "args": json.dumps({"q": "hello"})},
            {"type": "done", "content": ""},
        ]
        r2 = [
            {"type": "content", "text": "Writing. "},
            {"type": "tool_call", "tool": "write",
             "args": json.dumps({"content": "hello"})},
            {"type": "done", "content": ""},
        ]
        r3 = [
            {"type": "content", "text": "Done."},
            {"type": "done", "content": "Done."},
        ]

        call_count = {"n": 0}
        async def _astream(messages, tools=None):
            idx = call_count["n"]
            response = [r1, r2, r3][idx] if idx < 3 else [
                {"type": "done", "content": ""}
            ]
            call_count["n"] += 1
            for ev in response:
                yield ev

        wiki = _ReactMockWikiService(llm_events=[], tool_result={"result": "ok"})
        wiki.llm.astream_chat = _astream
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)

        out: list[dict] = []
        async for ev in chat.chat(message="do stuff", session_id="s1"):
            out.append(ev)

        # LLM was called 3 times
        assert call_count["n"] == 3

        # Two tool_call_start events (search + write)
        starts = [e for e in out if e.get("type") == "tool_call_start"]
        assert len(starts) == 2
        assert starts[0]["tool"] == "search"
        assert starts[1]["tool"] == "write"

        # Two tool_call_end events
        ends = [e for e in out if e.get("type") == "tool_call_end"]
        assert len(ends) == 2

        # Done event with the final answer
        done_events = [e for e in out if e.get("type") == "done"]
        assert len(done_events) == 1
        assert done_events[0]["final_response"] == "Done."

    @pytest.mark.asyncio
    async def test_react_path_handles_no_wiki(
        self, data_dir: Path,
    ) -> None:
        wiki = _ReactMockWikiService(llm_events=[])
        wiki.get_wiki = MagicMock(return_value=None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)

        out: list[dict] = []
        async for ev in chat.chat(message="hi", session_id="s1"):
            out.append(ev)

        types = [e.get("type") for e in out]
        assert "error" in types

    def test_translate_react_event_filters_internals(
        self, data_dir: Path,
    ) -> None:
        wiki = _ReactMockWikiService()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)
        ctx = AgentContext(wiki_id="w1")

        # Internal events should return None
        assert chat._translate_react_event(
            {"type": "reasoning", "action": "x", "thought": "y"},
            ctx, "s1",
        ) is None
        assert chat._translate_react_event(
            {"type": "round_complete", "round": 0, "action": "x"},
            ctx, "s1",
        ) is None

    def test_translate_react_event_action_error(
        self, data_dir: Path,
    ) -> None:
        wiki = _ReactMockWikiService()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            chat = ChatService(wiki, data_dir, use_react_engine=True)
        ctx = AgentContext(wiki_id="w1")

        result = chat._translate_react_event(
            {"type": "action_error", "action": "search", "error": "boom"},
            ctx, "s1",
        )
        assert result is not None
        assert result["type"] == "tool_call_error"
        assert result["tool"] == "search"
        assert result["error"] == "boom"
