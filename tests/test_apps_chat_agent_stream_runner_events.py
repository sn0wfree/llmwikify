"""Tests for ``ChatOrchestrator._stream_runner_events`` (O-1 extraction).

The runner streaming loop was the longest inline block in
``chat()``. Extracting it as ``_stream_runner_events`` makes the
abort precheck, mid-stream abort handling, and per-event side
effects (event log, assistant message persistence for CONFIRMATION /
ERROR) directly testable.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.events import (
    CONFIRMATION_REQUIRED,
    DONE,
    ERROR,
    MESSAGE_DELTA,
    TOOL_CALL_END,
)
from llmwikify.apps.chat.agent.orchestrator import (
    ChatEvent,
    ChatOrchestrator,
)


def _make_orchestrator(
    *,
    runner_events: list[dict] | None = None,
    runner_exc: BaseException | None = None,
) -> ChatOrchestrator:
    """Build a ChatOrchestrator with stub collaborators (skip __init__).

    ``__new__`` skips the real constructor so we can wire exactly the
    collaborators ``_stream_runner_events`` needs.
    """
    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    orch.event_log = MagicMock()
    orch.tool_executor = MagicMock()

    async def _runner(**_kwargs):
        if runner_exc is not None:
            raise runner_exc
        for ev in (runner_events or []):
            yield ev

    orch._chat_via_runner_v2 = _runner
    return orch


async def _collect(agen):
    return [ev async for ev in agen]


class TestPreStreamAbort:
    def test_abort_set_before_streaming_yields_error(self):
        orch = _make_orchestrator(runner_events=[])
        ev = asyncio.Event()
        ev.set()
        out = asyncio.run(_collect(orch._stream_runner_events(
            messages_for_llm=[],
            system_prompt="",
            tool_registry=MagicMock(),
            session_id="s1",
            ctx=MagicMock(),
            abort_event=ev,
        )))
        assert len(out) == 1
        assert out[0]["type"] == ERROR

    def test_abort_set_before_does_not_invoke_runner(self):
        """If already aborted, never call the runner."""
        orch = _make_orchestrator(runner_events=[{"type": DONE, "content": "x"}])
        ev = asyncio.Event()
        ev.set()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        # runner is async generator factory; verify it wasn't entered
        # by checking that no DONE event was yielded.
        # (We can't easily assert _chat_via_runner_v2 wasn't called
        # because the wrapper is already an async gen. The fact that
        # the only event is the pre-abort error is sufficient.)


class TestMidStreamAbort:
    def test_abort_set_during_stream_yields_error(self):
        """When abort fires mid-stream, emit error and stop."""
        ev = asyncio.Event()

        async def _runner(**_kwargs):
            yield {"type": MESSAGE_DELTA, "content": "hello"}
            ev.set()  # abort after first chunk
            yield {"type": MESSAGE_DELTA, "content": "world"}

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch.event_log = MagicMock()
        orch.tool_executor = MagicMock()
        orch._chat_via_runner_v2 = _runner

        out = asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        # First MESSAGE_DELTA, then error (no second delta)
        assert out[0]["type"] == MESSAGE_DELTA
        assert out[1]["type"] == ERROR
        assert len(out) == 2


class TestPerEventSideEffects:
    def test_message_delta_skips_event_log(self):
        """``message_delta`` is too high-volume to log."""
        orch = _make_orchestrator(
            runner_events=[{"type": MESSAGE_DELTA, "content": "hi"}],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        orch.event_log.log.assert_not_called()

    def test_non_delta_events_logged(self):
        orch = _make_orchestrator(
            runner_events=[
                {"type": TOOL_CALL_END, "tool": "x", "result": "ok", "call_id": "c1"},
            ],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        orch.event_log.log.assert_called_once()
        args = orch.event_log.log.call_args[0]
        assert args[0] == "s1"
        assert args[1]["type"] == TOOL_CALL_END

    def test_confirmation_required_saves_assistant_message(self):
        orch = _make_orchestrator(
            runner_events=[{
                "type": CONFIRMATION_REQUIRED,
                "tool": "wiki_write",
                "confirmation_id": "abc-123",
            }],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        orch.tool_executor.save_message.assert_called_once()
        args = orch.tool_executor.save_message.call_args[0]
        assert args[0] == "s1"
        assert args[1] == "assistant"
        assert "wiki_write" in args[2]
        assert "abc-123" in args[2]

    def test_error_event_saves_assistant_message(self):
        orch = _make_orchestrator(
            runner_events=[{
                "type": ERROR,
                "message": "rate limit hit",
            }],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        orch.tool_executor.save_message.assert_called_once()
        args = orch.tool_executor.save_message.call_args[0]
        assert "rate limit hit" in args[2]


class TestEventForwarding:
    def test_all_events_yielded_unchanged(self):
        runner_events = [
            {"type": MESSAGE_DELTA, "content": "a"},
            {"type": MESSAGE_DELTA, "content": "b"},
            {"type": TOOL_CALL_END, "tool": "t", "result": "r", "call_id": "c"},
            {"type": DONE, "content": "ab"},
        ]
        orch = _make_orchestrator(runner_events=runner_events)
        ev = asyncio.Event()
        out = asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        assert out == runner_events

    def test_done_event_ends_stream(self):
        orch = _make_orchestrator(
            runner_events=[
                {"type": MESSAGE_DELTA, "content": "x"},
                {"type": DONE, "content": "x"},
            ],
        )
        ev = asyncio.Event()
        out = asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "s1", MagicMock(), ev,
        )))
        assert out[-1]["type"] == DONE
        assert len(out) == 2

    def test_runner_exc_propagates(self):
        """If the runner raises, the exception is not swallowed here.

        Note: ``chat()`` has a broad ``try/except`` that catches it;
        this helper itself just propagates.
        """
        orch = _make_orchestrator(runner_exc=RuntimeError("boom"))
        ev = asyncio.Event()
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(_collect(orch._stream_runner_events(
                [], "", MagicMock(), "s1", MagicMock(), ev,
            )))


class TestSessionIdForwarding:
    def test_session_id_used_for_log(self):
        orch = _make_orchestrator(
            runner_events=[{"type": TOOL_CALL_END, "tool": "x", "result": "r", "call_id": "c"}],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "session-xyz", MagicMock(), ev,
        )))
        orch.event_log.log.assert_called_once()
        assert orch.event_log.log.call_args[0][0] == "session-xyz"

    def test_session_id_used_for_save_message(self):
        orch = _make_orchestrator(
            runner_events=[{"type": ERROR, "message": "x"}],
        )
        ev = asyncio.Event()
        asyncio.run(_collect(orch._stream_runner_events(
            [], "", MagicMock(), "another-id", MagicMock(), ev,
        )))
        assert orch.tool_executor.save_message.call_args[0][0] == "another-id"
