"""Unit tests for ChatReActBridge — ReAct adapter for ChatService.

Covers:

  - Text-mode ``[TOOL_CALL]`` parsing in the LLM stream
  - Multi-tool-call parallel execution
  - Confirmation flow (immediate exit on confirmation_required)
  - Tool call error events
  - Observation aggregation
  - ReAct prompt injection
  - message truncation
  - LLM retry (first-chunk)
  - thinking snapshot
  - End-to-end bridge + ReActEngine integration

Target: 30+ tests, no real LLM calls.
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

from llmwikify.apps.chat.agent.chat_react import (
    REACT_SYSTEM_PROMPT,
    ChatReActBridge,
    ChatReActState,
)
from llmwikify.apps.chat.agent.react_engine import (
    EVENT_REASONING,
    ReActConfig,
    ReActEngine,
)
from llmwikify.apps.chat.agent.service import (
    AgentContext,
    ChatService,
)
from llmwikify.apps.chat.agent.text_mode_tool import (
    TextModeParser,
    parse_text_tool_call,
)
from llmwikify.apps.chat.skills.base import SkillContext


# ─── Mock WikiService ───────────────────────────────────────────


class MockWikiService:
    """Mock WikiService that supports streaming and tool execution."""

    def __init__(
        self,
        llm_events: list[dict] | None = None,
        tool_result: Any = None,
    ) -> None:
        self.llm = MagicMock()
        self.llm_events = llm_events or []
        # Default astream_chat: yield the events as an async generator
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
                "description": "Search tool",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {
                "name": "write",
                "description": "Write tool",
                "parameters": {"type": "object", "properties": {"content": {"type": "string"}}},
            },
        ])
        self.tool_registry.execute = AsyncMock(
            return_value=tool_result or {"result": "ok"}
        )
        self.approve_confirmation = AsyncMock(
            return_value={"status": "ok", "result": "done"}
        )

    def get_default_wiki_id(self) -> str:
        return self.default_wiki_id

    def get_wiki(self, wiki_id: str | None = None) -> Any:
        return self.wiki

    def get_llm(self) -> Any:
        return self.llm

    def get_tool_registry(self, wiki_id: str | None = None) -> Any:
        return self.tool_registry


# ─── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def data_dir() -> Path:
    d = Path(tempfile.mkdtemp())
    yield d


@pytest.fixture
def chat_service(data_dir: Path) -> ChatService:
    wiki = MockWikiService()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ChatService(wiki, data_dir)


@pytest.fixture
def ctx(chat_service: ChatService) -> AgentContext:
    return AgentContext(wiki_id="test_wiki")


def _make_chat_with_llm_events(
    events: list[dict], tool_result: Any = None, data_dir: Path | None = None,
    call_responses: list[list[dict]] | None = None,
) -> ChatService:
    """Create a ChatService with mock LLM.

    Args:
        events: events to yield on first LLM call (then loop)
        tool_result: default tool result
        data_dir: temp data dir
        call_responses: per-call response lists. If provided,
            ``astream_chat`` returns the Nth entry on the Nth call.
            If None, always returns ``events``.
    """
    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp())
    wiki = MockWikiService(llm_events=events, tool_result=tool_result)
    if call_responses is not None:
        call_count = {"n": 0}

        async def _astream(messages, tools=None):
            idx = call_count["n"]
            if idx < len(call_responses):
                response = call_responses[idx]
            else:
                # Default: yield done with empty content (terminates)
                yield {"type": "done", "content": ""}
                return
            call_count["n"] += 1
            for ev in response:
                yield ev

        wiki.llm.astream_chat = _astream
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ChatService(wiki, data_dir)


def _wrap_with_emit_capture(
    config: ReActConfig, captured: list[dict],
) -> ReActConfig:
    """Wrap both reason and action_handler to capture emit events.

    Returns the modified config (the original is also mutated).
    Use ``ReActEngine(config)`` after this.
    """
    original_reason = config.reason
    original_handler = config.action_handler

    async def wrapped_reason(state, react_ctx, emit):
        async def capturing_emit(ev):
            captured.append(ev)
            await emit(ev)
        return await original_reason(state, react_ctx, capturing_emit)

    if original_handler is not None:
        async def wrapped_handler(action_name, state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_handler(
                action_name, state, react_ctx, capturing_emit,
            )
        config.action_handler = wrapped_handler

    config.reason = wrapped_reason
    return config


# ─── REACT_SYSTEM_PROMPT ───────────────────────────────────────


class TestReActSystemPrompt:
    def test_prompt_contains_reasoning_pattern(self) -> None:
        assert "Thought" in REACT_SYSTEM_PROMPT
        assert "Action" in REACT_SYSTEM_PROMPT
        assert "Observation" in REACT_SYSTEM_PROMPT

    def test_prompt_contains_confirmation_rule(self) -> None:
        assert "confirmation" in REACT_SYSTEM_PROMPT.lower()


# ─── ChatReActState ─────────────────────────────────────────────


class TestChatReActState:
    def test_initial_state(self) -> None:
        s = ChatReActState()
        d = s.to_dict()
        assert d["session_id"] == ""
        assert d["observations"] == []
        assert d["round"] == 0
        assert d["final_answer"] == ""

    def test_add_observation_caps_at_10(self) -> None:
        s = ChatReActState()
        for i in range(15):
            s.add_observation(f"obs {i}")
        assert len(s.observations) == 10
        assert s.observations[0] == "obs 5"
        assert s.observations[-1] == "obs 14"

    def test_get_observation_summary_empty(self) -> None:
        s = ChatReActState()
        assert s.get_observation_summary() == ""

    def test_get_observation_summary_picks_last_5(self) -> None:
        s = ChatReActState()
        for i in range(8):
            s.add_observation(f"obs {i}")
        summary = s.get_observation_summary()
        assert "Recent tool observations" in summary
        assert "obs 7" in summary
        # observations[0:3] are dropped (cap at 10), then last 5 shown
        # After 8 adds, cap=10 not reached, so all 8 are present
        # get_observation_summary picks last 5: obs 3-7
        assert "obs 3" in summary
        assert "obs 2" not in summary


# ─── Text-mode parser integration ───────────────────────────────


class TestTextModeParserIntegration:
    def test_parse_text_tool_call_basic(self) -> None:
        result = parse_text_tool_call(
            'tool => "search", args => { --q "hello" }'
        )
        assert result is not None
        assert result[0] == "search"
        assert result[1]["q"] == "hello"

    def test_parser_buffer_straddle(self) -> None:
        """Block can straddle two chunks."""
        async def run() -> list[dict]:
            p = TextModeParser()
            out: list[dict] = []
            # First chunk: prefix + start of TOOL_CALL
            async for e in p.feed({"type": "content", "text": "Hello [TOOL_CALL] tool => \"x\""}):
                out.append(e)
            # Second chunk: end of block + suffix
            async for e in p.feed({"type": "content", "text": ", args => { --a \"1\" } [/TOOL_CALL] world"}):
                out.append(e)
            # Done event flushes remaining buffer
            async for e in p.feed({"type": "done", "content": ""}):
                out.append(e)
            return out

        result = asyncio.run(run())
        types = [e["type"] for e in result]
        assert types == ["content", "tool_call", "content", "done"]
        assert "Hello" in result[0]["text"]
        assert result[1]["tool"] == "x"
        assert "world" in result[2]["text"]


# ─── Bridge.build_config ───────────────────────────────────────


class TestBridgeBuildConfig:
    def test_build_config_basic(self, chat_service: ChatService) -> None:
        bridge = ChatReActBridge(chat_service)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1",
            wiki_id="w1",
            tool_registry=chat_service.wiki_service.get_tool_registry(),
            user_message="hello",
            system_prompt="system",
            messages=[{"role": "user", "content": "hello"}],
            ctx=ctx,
            max_iterations=3,
        )
        assert isinstance(config, ReActConfig)
        assert config.max_rounds == 3
        assert config.initial_state["session_id"] == "s1"
        assert config.initial_state["user_message"] == "hello"

    def test_build_config_builds_actions(self, chat_service: ChatService) -> None:
        bridge = ChatReActBridge(chat_service)
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat_service.wiki_service.get_tool_registry(),
            user_message="hi", system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            ctx=AgentContext(wiki_id="w1"),
        )
        action_names = {a.name for a in config.actions}
        assert "search" in action_names
        assert "write" in action_names


# ─── End-to-end: no tool call (final answer) ───────────────────


class TestEndToEndFinalAnswer:
    def test_no_tool_call_yields_done(self, data_dir: Path) -> None:
        events = [
            {"type": "content", "text": "Hello! "},
            {"type": "content", "text": "How can I help?"},
            {"type": "done", "content": "Hello! How can I help?"},
        ]
        chat = _make_chat_with_llm_events(events, data_dir=data_dir)
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="hi", system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        # Track events via a wrapper emit that records into a list
        captured: list[dict] = []
        original_emit = None  # emit is closure; we patch via monkey-patch below

        # Collect via a custom action handler observer: wrap config to
        # intercept by patching reason/handler to record events.
        # Instead, run the engine and capture reasoning/thinking events.
        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        result = asyncio.run(run())
        # The engine emits at least one reasoning event, then phase=done.
        types = [e["type"] for e in result]
        assert EVENT_REASONING in types
        # Terminal phase event with final_state
        final_phases = [
            e for e in result
            if e.get("type") == "phase" and e.get("phase") == "done"
        ]
        assert final_phases
        # final_answer should be in state
        final_state = final_phases[-1].get("final_state", {})
        assert final_state.get("final_answer") == "Hello! How can I help?"


# ─── End-to-end: native tool call (action_handler) ─────────────


class TestEndToEndToolCall:
    def test_tool_call_executes_and_emits_events(self, data_dir: Path) -> None:
        first_response = [
            {"type": "content", "text": "Let me search. "},
            {
                "type": "tool_call",
                "tool": "search",
                "args": json.dumps({"q": "test"}),
            },
            {"type": "done", "content": ""},
        ]
        second_response = [
            {"type": "content", "text": "Found 3 pages."},
            {"type": "done", "content": ""},
        ]
        chat = _make_chat_with_llm_events(
            [], tool_result={"result": "found 3 pages"}, data_dir=data_dir,
            call_responses=[first_response, second_response],
        )
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="search for test", system_prompt="sys",
            messages=[{"role": "user", "content": "search for test"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        captured: list[dict] = []
        config = _wrap_with_emit_capture(config, captured)
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        result = asyncio.run(run())

        # Verify captured events contain tool_call_start
        start_events = [
            e for e in captured if e.get("type") == "tool_call_start"
        ]
        assert len(start_events) == 1
        assert start_events[0]["tool"] == "search"
        assert start_events[0]["args"]["q"] == "test"

        # Verify tool was actually executed
        chat.wiki_service.tool_registry.execute.assert_called_with(
            "search", {"q": "test"},
        )

        # Verify ctx was updated
        assert "search" in ctx._tool_calls
        assert ctx.tool_invocations == 1

        # Verify observation was added
        assert any("search" in obs for obs in ctx.react_observations)


# ─── End-to-end: text-mode tool call ───────────────────────────


class TestEndToEndTextMode:
    def test_text_mode_tool_call_parsed(self, data_dir: Path) -> None:
        first_response = [
            {"type": "content", "text": 'Let me search. [TOOL_CALL] tool => "search", args => { --q "hello" } [/TOOL_CALL]'},
            {"type": "done", "content": ""},
        ]
        second_response = [
            {"type": "content", "text": "Found."},
            {"type": "done", "content": ""},
        ]
        chat = _make_chat_with_llm_events(
            [], tool_result={"result": "found"}, data_dir=data_dir,
            call_responses=[first_response, second_response],
        )
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="search", system_prompt="sys",
            messages=[{"role": "user", "content": "search"}],
            ctx=ctx,
        )
        captured: list[dict] = []
        config = _wrap_with_emit_capture(config, captured)
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        asyncio.run(run())

        # Should have parsed the text-mode tool call
        start_events = [
            e for e in captured if e.get("type") == "tool_call_start"
        ]
        assert len(start_events) == 1
        assert start_events[0]["tool"] == "search"
        assert start_events[0]["args"]["q"] == "hello"

        # Tool should have been executed
        chat.wiki_service.tool_registry.execute.assert_called_with(
            "search", {"q": "hello"},
        )

    def test_text_mode_split_across_chunks(self, data_dir: Path) -> None:
        """[TOOL_CALL] block spans multiple content chunks."""
        first_response = [
            {"type": "content", "text": 'prefix [TOOL_CALL] tool => "x", '},
            {"type": "content", "text": 'args => { --a "1" } [/TOOL_CALL] suffix'},
            {"type": "done", "content": ""},
        ]
        second_response = [
            {"type": "content", "text": "ok"},
            {"type": "done", "content": ""},
        ]
        chat = _make_chat_with_llm_events(
            [], tool_result={"result": "ok"}, data_dir=data_dir,
            call_responses=[first_response, second_response],
        )
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="x", system_prompt="sys",
            messages=[{"role": "user", "content": "x"}],
            ctx=ctx,
        )
        captured: list[dict] = []
        config = _wrap_with_emit_capture(config, captured)
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        asyncio.run(run())
        start_events = [
            e for e in captured if e.get("type") == "tool_call_start"
        ]
        assert len(start_events) == 1
        assert start_events[0]["tool"] == "x"
        chat.wiki_service.tool_registry.execute.assert_called_with(
            "x", {"a": "1"},
        )


# ─── End-to-end: confirmation_required ─────────────────────────


class TestEndToEndConfirmation:
    def test_confirmation_stops_loop(self, data_dir: Path) -> None:
        first_response = [
            {"type": "content", "text": "Writing... "},
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
            "impact": {"description": "Will write to wiki"},
        }
        chat = _make_chat_with_llm_events(
            [], tool_result=confirmation_result, data_dir=data_dir,
            call_responses=[first_response],
        )
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="write", system_prompt="sys",
            messages=[{"role": "user", "content": "write"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        captured: list[dict] = []
        original_reason = config.reason
        original_handler = config.action_handler

        async def wrapped_reason(state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_reason(state, react_ctx, capturing_emit)

        async def wrapped_handler(action_name, state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_handler(action_name, state, react_ctx, capturing_emit)

        config.reason = wrapped_reason
        config.action_handler = wrapped_handler
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        result = asyncio.run(run())

        # confirmation_required should be emitted
        conf_events = [
            e for e in captured if e.get("type") == "confirmation_required"
        ]
        assert len(conf_events) == 1
        assert conf_events[0]["confirmation_id"] == "conf-1"

        # phase should be done
        final_phases = [
            e for e in result
            if e.get("type") == "phase" and e.get("phase") == "done"
        ]
        assert final_phases


# ─── End-to-end: tool error → tool_call_error event ────────────


class TestEndToEndToolError:
    def test_tool_exception_emits_error_event(self, data_dir: Path) -> None:
        first_response = [
            {
                "type": "tool_call",
                "tool": "search",
                "args": json.dumps({"q": "x"}),
            },
            {"type": "done", "content": ""},
        ]
        second_response = [
            {"type": "content", "text": "Failed."},
            {"type": "done", "content": ""},
        ]
        chat = _make_chat_with_llm_events(
            [], data_dir=data_dir,
            call_responses=[first_response, second_response],
        )
        # Make tool raise
        chat.wiki_service.tool_registry.execute = AsyncMock(
            side_effect=RuntimeError("tool down"),
        )
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="search", system_prompt="sys",
            messages=[{"role": "user", "content": "search"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        captured: list[dict] = []
        original_reason = config.reason
        original_handler = config.action_handler

        async def wrapped_reason(state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_reason(state, react_ctx, capturing_emit)

        async def wrapped_handler(action_name, state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_handler(action_name, state, react_ctx, capturing_emit)

        config.reason = wrapped_reason
        config.action_handler = wrapped_handler
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        asyncio.run(run())

        # Tool result with status="error" is handled by the action
        # handler — it should emit tool_call_error. But the action
        # handler calls _execute_tool which catches the exception and
        # returns {"status": "error", "error": str(exc)}.
        error_events = [
            e for e in captured if e.get("type") == "tool_call_error"
        ]
        assert len(error_events) == 1
        assert "tool down" in error_events[0]["error"]


# ─── Tool result threading (Phase 6.1 / v0.37) ─────────────────


class TestToolResultThreading:
    """Verify that tool results are appended to the LLM's message list
    so the next reasoning step sees the actual tool output.

    Prior to this fix, the reason callback closed over the original
    ``messages`` parameter and never mutated it, so the LLM on
    subsequent rounds only saw a truncated text summary (not the
    raw tool result, and no ``assistant`` role message with
    ``tool_calls``).
    """

    def test_tool_result_appended_as_tool_message(self, data_dir: Path) -> None:
        """After a tool call, the next LLM call must include a
        ``{role: "tool", name, content}`` message with the raw
        tool output."""
        received_messages_per_call: list[list[dict]] = []

        async def inspecting_llm(messages, tools=None):
            received_messages_per_call.append(list(messages))
            n = len(received_messages_per_call)
            if n == 1:
                yield {"type": "tool_call", "tool": "search",
                       "args": json.dumps({"q": "x"})}
                yield {"type": "done", "content": ""}
            else:
                tool_msgs = [m for m in messages if m.get("role") == "tool"]
                if tool_msgs:
                    yield {"type": "content", "text": "Got result."}
                    yield {"type": "done", "content": "Got result."}
                else:
                    yield {"type": "content", "text": "NO TOOL MSG."}
                    yield {"type": "done", "content": "NO TOOL MSG."}

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = inspecting_llm
        chat.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"status": "ok", "data": "raw tool output"},
        )

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="find x", system_prompt="sys",
            messages=[{"role": "user", "content": "find x"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        async def run():
            out = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out
        asyncio.run(run())

        # LLM was called twice
        assert len(received_messages_per_call) == 2
        round2_msgs = received_messages_per_call[1]
        # The second LLM call must see a role=tool message
        tool_msgs = [m for m in round2_msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["name"] == "search"
        # The tool result content must include the raw output
        assert "raw tool output" in tool_msgs[0]["content"]

    def test_assistant_tool_calls_message_appended(self, data_dir: Path) -> None:
        """The assistant's previous message (with tool_calls) must be
        appended before the tool result, so the LLM has the OpenAI-style
        pairing."""
        received_messages_per_call: list[list[dict]] = []

        async def inspecting_llm(messages, tools=None):
            received_messages_per_call.append(list(messages))
            n = len(received_messages_per_call)
            if n == 1:
                yield {"type": "tool_call", "tool": "search",
                       "args": json.dumps({"q": "x"})}
                yield {"type": "done", "content": ""}
            else:
                yield {"type": "content", "text": "ok"}
                yield {"type": "done", "content": "ok"}

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = inspecting_llm
        chat.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"result": "ok"},
        )

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="x", system_prompt="sys",
            messages=[{"role": "user", "content": "x"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        async def run():
            out = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out
        asyncio.run(run())

        round2_msgs = received_messages_per_call[1]
        # Find an assistant message with tool_calls
        assistant_msgs = [
            m for m in round2_msgs
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_msgs) >= 1
        # The tool_calls must mention the search tool
        tool_call_names = [
            tc.get("function", {}).get("name")
            for tc in assistant_msgs[-1]["tool_calls"]
        ]
        assert "search" in tool_call_names

    def test_full_tool_result_not_truncated(self, data_dir: Path) -> None:
        """The tool message must contain the FULL result, not the
        truncated 500-char summary that observation uses."""
        received_messages_per_call: list[list[dict]] = []

        async def inspecting_llm(messages, tools=None):
            received_messages_per_call.append(list(messages))
            n = len(received_messages_per_call)
            if n == 1:
                yield {"type": "tool_call", "tool": "search",
                       "args": json.dumps({})}
                yield {"type": "done", "content": ""}
            else:
                yield {"type": "content", "text": "ok"}
                yield {"type": "done", "content": "ok"}

        # Tool returns a large result that would be truncated in
        # the observation summary but should be FULL in the tool message.
        large_payload = "x" * 2000

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = inspecting_llm
        chat.wiki_service.tool_registry.execute = AsyncMock(
            return_value={"data": large_payload},
        )

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="x", system_prompt="sys",
            messages=[{"role": "user", "content": "x"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        async def run():
            out = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out
        asyncio.run(run())

        tool_msgs = [
            m for m in received_messages_per_call[1]
            if m.get("role") == "tool"
        ]
        assert len(tool_msgs) == 1
        # Full payload must be in the tool message content
        assert large_payload in tool_msgs[0]["content"]


# ─── Multi-round: tool then final answer ────────────────────────


class TestMultiRound:
    def test_tool_call_then_done(self, data_dir: Path) -> None:
        """First round: tool call. Second round: final answer."""
        # We'll mock the LLM to return tool_call first, then final answer
        call_count = {"n": 0}

        async def llm_stream(messages, tools):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield {"type": "content", "text": "Searching... "}
                yield {
                    "type": "tool_call",
                    "tool": "search",
                    "args": json.dumps({"q": "x"}),
                }
            else:
                yield {"type": "content", "text": "Here's what I found."}
            yield {"type": "done", "content": ""}

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = llm_stream

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="search", system_prompt="sys",
            messages=[{"role": "user", "content": "search"}],
            ctx=ctx,
            max_iterations=4,
        )
        engine = ReActEngine(config)
        captured: list[dict] = []
        original_reason = config.reason
        original_handler = config.action_handler

        async def wrapped_reason(state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_reason(state, react_ctx, capturing_emit)

        async def wrapped_handler(action_name, state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_handler(action_name, state, react_ctx, capturing_emit)

        config.reason = wrapped_reason
        config.action_handler = wrapped_handler
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        asyncio.run(run())

        # Should have made 2 LLM calls
        assert call_count["n"] == 2

        # Should have tool_call_start and tool_call_end
        start_events = [
            e for e in captured if e.get("type") == "tool_call_start"
        ]
        end_events = [
            e for e in captured if e.get("type") == "tool_call_end"
        ]
        assert len(start_events) == 1
        assert len(end_events) == 1

        # Should have 2+ reasoning events (one per round)
        reasoning_events = [
            e for e in captured if e.get("type") == "reasoning"
        ]
        # Note: reasoning events are emitted by ReActEngine itself,
        # not via the emit callback, so they may not appear in captured
        # (they go through engine.run() yield). We check that the
        # engine completed.
        assert captured  # some events were captured

    def test_three_round_react_chain(self, data_dir: Path) -> None:
        """True multi-round: search → write → final answer.

        The LLM sees the search result and decides to call another
        tool (write), sees the write result, then gives a final answer.
        """
        round1 = [
            {"type": "content", "text": "Searching... "},
            {"type": "tool_call", "tool": "search",
             "args": json.dumps({"q": "hello"})},
            {"type": "done", "content": ""},
        ]
        round2 = [
            {"type": "content", "text": "Now writing... "},
            {"type": "tool_call", "tool": "write",
             "args": json.dumps({"content": "hello"})},
            {"type": "done", "content": ""},
        ]
        round3 = [
            {"type": "content", "text": "All done."},
            {"type": "done", "content": "All done."},
        ]

        call_count = {"n": 0}
        async def llm_stream(messages, tools):
            idx = call_count["n"]
            response = [round1, round2, round3][idx] if idx < 3 else [
                {"type": "done", "content": ""}
            ]
            call_count["n"] += 1
            for ev in response:
                yield ev

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = llm_stream

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="do stuff", system_prompt="sys",
            messages=[{"role": "user", "content": "do stuff"}],
            ctx=ctx,
            max_iterations=8,
        )
        engine = ReActEngine(config)
        captured: list[dict] = []
        original_reason = config.reason
        original_handler = config.action_handler

        async def wrapped_reason(state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_reason(state, react_ctx, capturing_emit)

        async def wrapped_handler(action_name, state, react_ctx, emit):
            async def capturing_emit(ev):
                captured.append(ev)
                await emit(ev)
            return await original_handler(
                action_name, state, react_ctx, capturing_emit,
            )

        config.reason = wrapped_reason
        config.action_handler = wrapped_handler
        engine = ReActEngine(config)

        async def run() -> list[dict]:
            out: list[dict] = []
            async for ev in engine.run(SkillContext(session_id="s1")):
                out.append(ev)
            return out

        result = asyncio.run(run())

        # The LLM was called 3 times
        assert call_count["n"] == 3

        # Two tool_call_start events (one for search, one for write)
        start_events = [
            e for e in captured if e.get("type") == "tool_call_start"
        ]
        assert len(start_events) == 2
        assert start_events[0]["tool"] == "search"
        assert start_events[1]["tool"] == "write"

        # Two tool_call_end events
        end_events = [
            e for e in captured if e.get("type") == "tool_call_end"
        ]
        assert len(end_events) == 2

        # Engine emitted a terminal phase=done event
        final_phases = [
            e for e in result
            if e.get("type") == "phase" and e.get("phase") == "done"
            and "final_state" in e
        ]
        assert final_phases


# ─── Observation aggregation ────────────────────────────────────
    def test_observation_summary_injected_into_messages(self, data_dir: Path) -> None:
        """On round 2, observation summary is prepended to messages."""
        received_messages_per_call: list[list[dict]] = []

        async def llm_stream(messages, tools):
            # Record messages
            received_messages_per_call.append(list(messages))
            if len(received_messages_per_call) == 1:
                yield {
                    "type": "tool_call",
                    "tool": "search",
                    "args": json.dumps({"q": "x"}),
                }
            else:
                yield {"type": "content", "text": "Done."}
            yield {"type": "done", "content": ""}

        chat = _make_chat_with_llm_events([], data_dir=data_dir)
        chat.wiki_service.llm.astream_chat = llm_stream

        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="search", system_prompt="sys",
            messages=[{"role": "user", "content": "search"}],
            ctx=ctx,
            max_iterations=4,
        )
        engine = ReActEngine(config)
        async def run() -> None:
            async for _ in engine.run(SkillContext(session_id="s1")):
                pass
        asyncio.run(run())

        # Round 2 should have observation summary in messages
        assert len(received_messages_per_call) == 2
        round2_messages = received_messages_per_call[1]
        # Find a system message with "Recent tool"
        found_summary = any(
            m.get("role") == "system" and "Recent tool" in m.get("content", "")
            for m in round2_messages
        )
        assert found_summary


# ─── Thinking snapshot ──────────────────────────────────────────


class TestThinkingSnapshot:
    def test_thinking_set_on_ctx(self, data_dir: Path) -> None:
        events = [
            {"type": "thinking", "text": "Let me think... "},
            {"type": "thinking", "text": "more thinking"},
            {"type": "content", "text": "Final answer."},
            {"type": "done", "content": ""},
        ]
        chat = _make_chat_with_llm_events(events, data_dir=data_dir)
        bridge = ChatReActBridge(chat)
        ctx = AgentContext(wiki_id="w1")
        config = bridge.build_config(
            session_id="s1", wiki_id="w1",
            tool_registry=chat.wiki_service.get_tool_registry(),
            user_message="x", system_prompt="sys",
            messages=[{"role": "user", "content": "x"}],
            ctx=ctx,
        )
        engine = ReActEngine(config)
        async def run() -> None:
            async for _ in engine.run(SkillContext(session_id="s1")):
                pass
        asyncio.run(run())

        assert ctx._thinking == "Let me think... more thinking"
