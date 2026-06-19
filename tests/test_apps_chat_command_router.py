"""Tests for the CommandRouter vendored from nanobot (P1-2).

Covers:
  - Registration API (priority / exact / prefix)
  - 3-tier dispatch: priority > exact > prefix > unhandled
  - is_priority / is_command classification
  - Longest-prefix-wins ordering
  - CommandContext mutation by prefix handlers (ctx.args is set)
  - Handler return-shape normalisation (None / dict / list / async iter)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.command_router import (
    CommandContext,
    CommandRouter,
)

# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_priority_register(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: {"type": "stop"})
        assert "/stop" in r._priority
        assert r.is_priority("/stop") is True
        assert r.is_priority("/Stop") is True  # case-insensitive

    def test_exact_register(self):
        r = CommandRouter()
        r.exact("/help", lambda ctx: {"type": "help"})
        assert "/help" in r._exact
        assert "/help" not in r._priority

    def test_prefix_register_sorted_longest_first(self):
        r = CommandRouter()
        r.prefix("/model", lambda ctx: {})
        r.prefix("/model-pro", lambda ctx: {})
        # longest prefix first
        assert r._prefix[0][0] == "/model-pro"
        assert r._prefix[1][0] == "/model"

    def test_prefix_register_idempotent(self):
        r = CommandRouter()
        r.prefix("/x", lambda ctx: {})
        r.prefix("/x", lambda ctx: {})
        # Same prefix registered twice → 2 entries (no de-dup).
        # Tests the documented behaviour so a future de-dup is intentional.
        assert len(r._prefix) == 2

    def test_memory_dream_registered_by_default(self) -> None:
        """Phase 6 (2026-06-19): /memory_dream should be registered
        as a prefix command in the orchestrator's default router."""
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

        # Build an instance with default router (no full DB / LLM)
        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.command_router = orch._build_default_command_router()
        assert orch.command_router.is_command("/memory_dream")
        assert orch.command_router.is_command("/memory_dream session abc")
        assert orch.command_router.is_command("/MEMORY_DREAM")  # case-insensitive


# ---------------------------------------------------------------------------
# 2. Classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_is_priority(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: None)
        assert r.is_priority("/stop") is True
        assert r.is_priority("/STOP") is True
        assert r.is_priority("  /stop  ") is True
        assert r.is_priority("/help") is False

    def test_is_command_priority_tier(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: None)
        assert r.is_command("/stop") is True

    def test_is_command_exact_tier(self):
        r = CommandRouter()
        r.exact("/help", lambda ctx: None)
        assert r.is_command("/help") is True
        assert r.is_command("/help me") is False

    def test_is_command_prefix_tier(self):
        r = CommandRouter()
        r.prefix("/model", lambda ctx: None)
        assert r.is_command("/model gpt-4o") is True
        assert r.is_command("/model") is True
        assert r.is_command("/mod") is False

    def test_is_command_no_match(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: None)
        r.exact("/help", lambda ctx: None)
        r.prefix("/model", lambda ctx: None)
        assert r.is_command("hello world") is False


# ---------------------------------------------------------------------------
# 3. Dispatch
# ---------------------------------------------------------------------------


def _ctx(text: str, **kwargs) -> CommandContext:
    """Build a CommandContext with sensible test defaults."""
    raw = text.strip().lower()
    return CommandContext(
        text=text,
        session_id=kwargs.get("session_id", "s1"),
        key=kwargs.get("key", "s1"),
        raw=raw,
        args=kwargs.get("args", ""),
    )


class TestDispatch:
    @pytest.mark.asyncio
    async def test_priority_dispatch(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: {"type": "stopped"})
        ctx = _ctx("/stop")
        result = await r.dispatch_priority(ctx)
        assert result == [{"type": "stopped"}]

    @pytest.mark.asyncio
    async def test_priority_dispatch_unhandled(self):
        r = CommandRouter()
        r.priority("/stop", lambda ctx: {"type": "stopped"})
        ctx = _ctx("/help")
        result = await r.dispatch_priority(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_exact_dispatch(self):
        r = CommandRouter()
        r.exact("/help", lambda ctx: {"type": "help_text", "text": "commands: ..."})
        ctx = _ctx("/help")
        result = await r.dispatch(ctx)
        assert result == [{"type": "help_text", "text": "commands: ..."}]

    @pytest.mark.asyncio
    async def test_exact_dispatch_case_insensitive(self):
        r = CommandRouter()
        r.exact("/help", lambda ctx: {"type": "help_text"})
        ctx = _ctx("/HELP")
        result = await r.dispatch(ctx)
        assert result == [{"type": "help_text"}]

    @pytest.mark.asyncio
    async def test_prefix_dispatch_strips_args(self):
        r = CommandRouter()
        captured = {}

        def handler(ctx: CommandContext) -> dict:
            captured["args"] = ctx.args
            return {"type": "model_set", "model": ctx.args.strip()}

        r.prefix("/model", handler)
        ctx = _ctx("/model gpt-4o")
        result = await r.dispatch(ctx)
        assert result == [{"type": "model_set", "model": "gpt-4o"}]
        assert captured["args"] == " gpt-4o"

    @pytest.mark.asyncio
    async def test_prefix_dispatch_preserves_case_in_args(self):
        """Args extracted from ``ctx.text`` retain their original case,
        even though ``ctx.raw`` is lowercased for matching."""
        r = CommandRouter()
        captured = {}

        def handler(ctx: CommandContext) -> dict:
            captured["args"] = ctx.args
            return {"type": "ok"}

        r.prefix("/title", handler)
        # Uppercase text + lowercased raw should still preserve case
        # in the extracted args.
        ctx = CommandContext(text="/title My Research", raw="/title my research")
        await r.dispatch(ctx)
        assert captured["args"] == " My Research"

    @pytest.mark.asyncio
    async def test_prefix_dispatch_longest_wins(self):
        r = CommandRouter()
        r.prefix("/model", lambda ctx: {"type": "model_default"})
        r.prefix("/model-pro", lambda ctx: {"type": "model_pro"})
        ctx = _ctx("/model-pro gpt-4o")
        result = await r.dispatch(ctx)
        assert result == [{"type": "model_pro"}]

    @pytest.mark.asyncio
    async def test_dispatch_unhandled(self):
        r = CommandRouter()
        r.exact("/help", lambda ctx: None)
        r.prefix("/model", lambda ctx: None)
        ctx = _ctx("/unknown")
        result = await r.dispatch(ctx)
        assert result == []


# ---------------------------------------------------------------------------
# 4. Handler return-shape normalisation
# ---------------------------------------------------------------------------


class TestHandlerReturnShapes:
    @pytest.mark.asyncio
    async def test_handler_returns_none(self):
        r = CommandRouter()
        r.exact("/noop", lambda ctx: None)
        ctx = _ctx("/noop")
        result = await r.dispatch(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_handler_returns_single_dict(self):
        r = CommandRouter()
        r.exact("/x", lambda ctx: {"type": "x_done"})
        ctx = _ctx("/x")
        result = await r.dispatch(ctx)
        assert result == [{"type": "x_done"}]

    @pytest.mark.asyncio
    async def test_handler_returns_list(self):
        r = CommandRouter()
        r.exact("/multi", lambda ctx: [
            {"type": "ev1"},
            {"type": "ev2"},
        ])
        ctx = _ctx("/multi")
        result = await r.dispatch(ctx)
        assert result == [{"type": "ev1"}, {"type": "ev2"}]

    @pytest.mark.asyncio
    async def test_handler_returns_async_iter(self):
        r = CommandRouter()

        async def handler(ctx: CommandContext):
            for i in range(3):
                yield {"type": "tick", "i": i}

        r.exact("/stream", handler)
        ctx = _ctx("/stream")
        result = await r.dispatch(ctx)
        assert result == [
            {"type": "tick", "i": 0},
            {"type": "tick", "i": 1},
            {"type": "tick", "i": 2},
        ]


# ---------------------------------------------------------------------------
# 5. Priority vs exact ordering
# ---------------------------------------------------------------------------


class TestPrioritySemantics:
    @pytest.mark.asyncio
    async def test_priority_does_not_match_via_dispatch(self):
        """Priority commands are NOT picked up by ``dispatch()`` — they
        must be invoked via ``dispatch_priority()`` (so callers can run
        them outside the dispatch lock)."""
        r = CommandRouter()
        r.priority("/stop", lambda ctx: {"type": "stopped"})
        r.exact("/stop", lambda ctx: {"type": "stopped_exact"})
        ctx = _ctx("/stop")
        # dispatch_priority sees priority handler
        result = await r.dispatch_priority(ctx)
        assert result == [{"type": "stopped"}]
        # dispatch sees only the exact handler
        result = await r.dispatch(ctx)
        assert result == [{"type": "stopped_exact"}]

    @pytest.mark.asyncio
    async def test_is_command_sees_priority(self):
        """``is_command`` covers all tiers (incl. priority) so the
        orchestrator can decide whether to call dispatch_priority."""
        r = CommandRouter()
        r.priority("/stop", lambda ctx: None)
        assert r.is_command("/stop") is True


# ---------------------------------------------------------------------------
# 6. CommandContext mutation
# ---------------------------------------------------------------------------


class TestCommandContextMutation:
    def test_args_mutation_visible_to_caller(self):
        ctx = CommandContext(text="/model gpt-4o", raw="/model gpt-4o")
        ctx.args = " gpt-4o"
        assert ctx.args == " gpt-4o"
        assert ctx.text == "/model gpt-4o"
        # ctx.raw is the lowercased command, untouched by the prefix mutation.
        assert ctx.raw == "/model gpt-4o"


# ---------------------------------------------------------------------------
# 7. Orchestrator integration (P1-2 wiring)
# ---------------------------------------------------------------------------


class TestOrchestratorCommandDispatch:
    """The orchestrator intercepts slash commands before the LLM loop runs."""

    def _make_orchestrator(self):
        """Build a bare ChatOrchestrator via __new__ to skip heavy __init__."""
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.db = MagicMock()
        orch.db.update_chat_session_title = MagicMock()
        orch.command_router = ChatOrchestrator._build_default_command_router(orch)
        return orch

    @pytest.mark.asyncio
    async def test_dispatch_non_command_yields_nothing(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="hello world",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        assert events == []

    @pytest.mark.asyncio
    async def test_dispatch_text_without_slash_yields_nothing(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="not a command",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        assert events == []

    @pytest.mark.asyncio
    async def test_dispatch_help_command(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="/help",
            session_id="s1",
            wiki_id="w1",
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        # First event is the help message; second is the dispatch_done marker.
        assert len(events) == 2
        assert events[0]["type"] == "command_done"
        assert events[0]["command"] == "/help"
        assert "Available commands" in events[0]["message"]
        assert events[1]["command"] == "/help"

    @pytest.mark.asyncio
    async def test_dispatch_stop_sets_abort_event(self):
        orch = self._make_orchestrator()
        abort = asyncio.Event()
        events = []
        async for ev in orch._dispatch_command(
            text="/stop",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=None,
            abort_event=abort,
        ):
            events.append(ev)
        assert abort.is_set() is True
        assert events[0]["command"] == "/stop"
        assert events[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_dispatch_clear_with_ctx(self):
        orch = self._make_orchestrator()
        ctx = MagicMock()
        events = []
        async for ev in orch._dispatch_command(
            text="/clear",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=ctx,
            abort_event=None,
        ):
            events.append(ev)
        assert ctx.clear.called
        assert events[0]["message"] == "Context cleared"

    @pytest.mark.asyncio
    async def test_dispatch_title_with_args(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="/title My Research",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        assert orch.db.update_chat_session_title.called
        call_args = orch.db.update_chat_session_title.call_args
        assert call_args.args == ("s1", "My Research")
        assert "Title set" in events[0]["message"]

    @pytest.mark.asyncio
    async def test_dispatch_title_without_args_reports_error(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="/title",
            session_id="s1",
            wiki_id=None,
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        # /title with no args returns ok=False, but still goes through
        # the prefix path (matches "/title" as a prefix of itself).
        assert events[0]["ok"] is False
        assert "Usage" in events[0]["message"]

    @pytest.mark.asyncio
    async def test_dispatch_status_reports_session(self):
        orch = self._make_orchestrator()
        events = []
        async for ev in orch._dispatch_command(
            text="/status",
            session_id="abc-123",
            wiki_id="mywiki",
            db=orch.db,
            ctx=None,
            abort_event=None,
        ):
            events.append(ev)
        assert "abc-123" in events[0]["message"]
        assert "mywiki" in events[0]["message"]


# ---------------------------------------------------------------------------
# 8. 3-tier integration: real chat flow skips LLM for commands
# ---------------------------------------------------------------------------


class TestCommandShortCircuitsLLMLoop:
    """Verify that a slash command does not reach the runner.

    We can't easily mock the full ReAct loop here, but we can verify
    the orchestrator's _dispatch_command is the first hook in chat()
    and that it produces a `command_done` event that the call site
    uses to short-circuit.
    """

    def test_command_router_present_on_orchestrator(self):
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator
        from llmwikify.apps.chat.command_router import CommandRouter

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.command_router = ChatOrchestrator._build_default_command_router(orch)
        assert isinstance(orch.command_router, CommandRouter)

    def test_default_router_has_5_builtin_commands(self):
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.command_router = ChatOrchestrator._build_default_command_router(orch)
        # /stop is priority; /help, /clear, /status are exact; /title is prefix.
        assert orch.command_router.is_command("/stop") is True
        assert orch.command_router.is_command("/help") is True
        assert orch.command_router.is_command("/clear") is True
        assert orch.command_router.is_command("/status") is True
        assert orch.command_router.is_command("/title anything") is True
        assert orch.command_router.is_command("hello") is False

    def test_custom_router_replaces_default(self):
        """Test that ``self.command_router`` is a swappable instance."""
        from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator
        from llmwikify.apps.chat.command_router import CommandRouter

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        custom = CommandRouter()
        custom.exact("/ping", lambda ctx: {"type": "pong"})
        orch.command_router = custom
        assert orch.command_router.is_command("/ping") is True
        assert orch.command_router.is_command("/help") is False
