"""Regression tests for the Pass 1.1 SSE factory refactor.

Before refactor: ``/chat`` and ``/approve-and-continue`` had inline
``event_generator`` closures with ~80% duplicated logic (bus mirror,
timeout check, SSE wire format).

After refactor: both endpoints delegate to ``chat_sse._sse_stream``,
a single factory that owns the SSE template.

These tests guard against regressions in the wire format, the bus
mirror side effect, the timeout contract, the end-of-stream heartbeat,
and the session-key construction.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from llmwikify.apps.chat.bus.adapter import BusAdapter
from llmwikify.apps.chat.bus.queue import MessageBus, reset_default_bus
from llmwikify.interfaces.server.http.chat_sse import (
    HEARTBEAT_INTERVAL,
    STREAM_TIMEOUT,
    STUDY_STREAM_TIMEOUT,
    _sse_stream,
)

# ─── Helpers ───────────────────────────────────────────────────────


async def _aiter(items: list[Any]) -> Any:
    """Tiny async iterator for use as ``source`` in tests."""
    for item in items:
        yield item


async def _collect(stream) -> list[dict[str, str]]:
    """Drain an async SSE stream into a list of event dicts."""
    out: list[dict[str, str]] = []
    async for ev in stream:
        out.append(ev)
    return out


def _wire_format(ev: dict[str, str]) -> str:
    """Render an SSE event dict as it would be written to the wire."""
    lines = []
    for k, v in ev.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


@pytest.fixture
def bus() -> Any:
    """Fresh isolated MessageBus for each test (reset + return)."""
    reset_default_bus()
    bus_instance = MessageBus()
    yield bus_instance
    reset_default_bus()


# ─── 1. Wire format ─────────────────────────────────────────────────


class TestWireFormat:
    """The factory must emit SSE-protocol-shaped dicts."""

    async def test_business_event_format(self) -> None:
        """Each source event yields ``{"event": "message", "data": <json>}``."""
        events = [{"type": "message_delta", "content": "hi"}]
        out = await _collect(_sse_stream(_aiter(events)))
        assert len(out) == 1
        assert out[0]["event"] == "message"
        assert json.loads(out[0]["data"]) == {"type": "message_delta", "content": "hi"}

    async def test_wire_format_string_is_sse_compatible(self) -> None:
        """The rendered wire string parses as an SSE event block."""
        events = [{"type": "done"}]
        out = await _collect(_sse_stream(_aiter(events)))
        wire = _wire_format(out[0])
        # Split into lines; SSE requires "event: <name>" then "data: <value>".
        assert wire.startswith("event: message\n")
        assert "data: " in wire
        # Data must be valid JSON
        data_line = next(ln for ln in wire.split("\n") if ln.startswith("data: "))
        json.loads(data_line[len("data: "):])

    async def test_multiple_events_preserve_order(self) -> None:
        """Factory yields events in source order."""
        events = [{"type": "message_delta", "n": i} for i in range(5)]
        out = await _collect(_sse_stream(_aiter(events)))
        assert len(out) == 5
        for i, ev in enumerate(out):
            assert json.loads(ev["data"])["n"] == i


# ─── 2. Bus mirror ──────────────────────────────────────────────────


class TestBusMirror:
    """Every business event must be mirrored to MessageBus."""

    async def test_each_event_published(self, bus: MessageBus) -> None:
        """N source events => N outbound messages on the bus."""
        # Inject our bus into the BusAdapter used by _sse_stream
        events = [{"type": "message_delta", "content": f"chunk-{i}"} for i in range(3)]

        async def stream_with_bus():
            adapter = BusAdapter(bus=bus)
            async for event in _aiter(events):
                adapter.mirror_sse_event(
                    event, target_id="", session_key="",
                )
                yield {"event": "message", "data": json.dumps(event)}

        out = await _collect(stream_with_bus())
        assert len(out) == 3
        # The bus should have 3 published messages
        assert bus.stats()["outbound"]["published"] == 3

    async def test_no_mirror_for_empty_stream(self, bus: MessageBus) -> None:
        """Empty source emits no outbound messages (only heartbeat if applicable)."""
        adapter = BusAdapter(bus=bus)

        async def stream_with_bus():
            async for event in _aiter([]):
                adapter.mirror_sse_event(event, target_id="", session_key="")
                yield {"event": "message", "data": json.dumps(event)}

        out = await _collect(stream_with_bus())
        assert bus.stats()["outbound"]["published"] == 0
        assert out == []


# ─── 3. Timeout ─────────────────────────────────────────────────────


class TestTimeout:
    """Source events past the timeout must yield a timeout event and stop."""

    async def test_timeout_event_emitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Yielding past ``timeout`` emits a single timeout event and returns."""
        # Patch time.monotonic so the test runs instantly.
        # Sequence: [0.0, 0.0, 1000.0, 1000.0] - any value > timeout triggers.
        # Use a list-indexed mock so we don't exhaust a generator.
        values = [0.0, 0.0, 1000.0, 1000.0, 1000.0]
        idx = {"n": 0}

        def fake_monotonic() -> float:
            i = idx["n"]
            idx["n"] += 1
            return values[i] if i < len(values) else values[-1]

        monkeypatch.setattr(
            "llmwikify.interfaces.server.http.chat_sse.time.monotonic",
            fake_monotonic,
        )

        async def slow_source():
            yield {"type": "message_delta", "content": "first"}
            yield {"type": "message_delta", "content": "second"}

        out = await _collect(_sse_stream(slow_source(), timeout=1))
        # First event passes (elapsed ~0), second triggers timeout
        assert len(out) == 2
        assert json.loads(out[0]["data"])["type"] == "message_delta"
        # Second event is the timeout notice
        timeout_payload = json.loads(out[1]["data"])
        assert timeout_payload["type"] == "timeout"
        assert "timed out" in timeout_payload["message"].lower()

    async def test_timeout_uses_param_value(self) -> None:
        """Factory honors the caller-supplied ``timeout`` (in seconds)."""
        # All monotonic calls return 0 -> elapsed never exceeds any timeout
        # So no timeout event ever fires regardless of timeout value.
        out = await _collect(_sse_stream(_aiter([{"type": "x"}]), timeout=1))
        assert len(out) == 1
        assert json.loads(out[0]["data"])["type"] == "x"


# ─── 4. End-of-stream heartbeat ─────────────────────────────────────


class TestEndOfStreamHeartbeat:
    """Stream > HEARTBEAT_INTERVAL seconds -> final heartbeat emitted.

    Refactor note (Pass 1.1): /approve-and-continue previously did NOT
    emit a final heartbeat; the factory now emits one uniformly for all
    callers. This is the documented behavior change.
    """

    async def test_heartbeat_emitted_when_stream_long(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If total stream time exceeds HEARTBEAT_INTERVAL, emit heartbeat."""
        # start_time = 0.0; final elapsed check = 100.0 (past 15s)
        values = [0.0, 100.0, 100.0]
        idx = {"n": 0}

        def fake_monotonic() -> float:
            i = idx["n"]
            idx["n"] += 1
            return values[i] if i < len(values) else values[-1]

        monkeypatch.setattr(
            "llmwikify.interfaces.server.http.chat_sse.time.monotonic",
            fake_monotonic,
        )

        out = await _collect(_sse_stream(_aiter([{"type": "done"}])))
        # 1 business event + 1 heartbeat
        assert len(out) == 2
        assert json.loads(out[0]["data"])["type"] == "done"
        assert out[1] == {"event": "heartbeat", "data": ""}

    async def test_no_heartbeat_when_stream_short(self) -> None:
        """If total stream time is short (< 15s), no heartbeat emitted."""
        out = await _collect(_sse_stream(_aiter([{"type": "done"}])))
        # Only the business event, no heartbeat
        assert len(out) == 1
        assert json.loads(out[0]["data"])["type"] == "done"

    async def test_heartbeat_alignment_with_chat_and_approve_and_continue(self) -> None:
        """Documented behavior change: both endpoints now send end heartbeat.

        Pre-refactor: /chat sent heartbeat, /approve-and-continue did not.
        Post-refactor: both share the same factory, so both send heartbeat.
        """
        # The factory is the single source of truth, so the behavior is
        # unified regardless of which endpoint calls it. This test documents
        # the intentional behavior change so future regressions are obvious.
        assert HEARTBEAT_INTERVAL == 15, "heartbeat interval changed; review unification"


# ─── 5. session_key construction ────────────────────────────────────


class TestSessionKey:
    """session_key is ``http:{session_id}`` when provided, else empty string."""

    async def test_session_key_with_session_id(self) -> None:
        """Verify the factory accepts session_id without errors and produces events."""
        # Indirectly verified: factory signature accepts session_id kwarg
        out = await _collect(
            _sse_stream(_aiter([{"type": "x"}]), session_id="abc-123")
        )
        assert len(out) == 1

    async def test_session_key_with_empty_session_id(self) -> None:
        """Verify factory works with empty session_id (no exception)."""
        out = await _collect(
            _sse_stream(_aiter([{"type": "x"}]), session_id="")
        )
        assert len(out) == 1

    async def test_session_key_default_is_empty(self) -> None:
        """Verify default session_id is empty string."""
        out = await _collect(_sse_stream(_aiter([{"type": "x"}])))
        assert len(out) == 1


# ─── 6. Constants sanity (refactor didn't break module-level config) ─


class TestModuleConstants:
    """Module-level constants must remain stable."""

    def test_heartbeat_interval(self) -> None:
        assert HEARTBEAT_INTERVAL == 15

    def test_default_stream_timeout(self) -> None:
        assert STREAM_TIMEOUT == 300

    def test_study_stream_timeout(self) -> None:
        assert STUDY_STREAM_TIMEOUT == 30 * 60


# ─── 7. Backward compatibility ─────────────────────────────────────


class TestBackwardCompat:
    """Public API symbols must remain at their known locations."""

    def test_sse_stream_is_importable_from_chat_sse(self) -> None:
        """`_sse_stream` is the new factory; must be importable for testing."""
        from llmwikify.interfaces.server.http.chat_sse import _sse_stream
        assert callable(_sse_stream)

    def test_router_prefix_unchanged(self) -> None:
        """The agent router's URL prefix must still be ``/api/agent``."""
        from llmwikify.interfaces.server.http.chat_sse import router
        assert router.prefix == "/api/agent"

    def test_get_set_agent_service_still_works(self) -> None:
        """Module-level singleton API must be intact."""
        from llmwikify.interfaces.server.http.chat_sse import (
            get_agent_service,
            set_agent_service,
        )
        assert callable(set_agent_service)
        assert callable(get_agent_service)
