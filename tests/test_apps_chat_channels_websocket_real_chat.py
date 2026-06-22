"""Phase 19-B — WebSocket real chat wire tests.

Covers:
  - WsSessionMap: get/set/discard/stats + default singleton
  - _handle_client_msg with orchestrator injection:
    - message routes to ChatOrchestrator.chat()
    - yields are mirrored to MessageBus
    - yields are translated to WS envelope
    - yields are fan-out via send_to_chat
    - session_created event caches session_id in WsSessionMap
    - multiple messages on same chat_id reuse session_id
    - missing chat_id still emits error envelope (backward compat)
  - echo fallback when orchestrator=None (dev mode)
  - orchestrator exception → best-effort error fan-out
  - SSE event types round-trip through BusAdapter.translate_sse_to_ws
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from llmwikify.apps.chat.bus import (
    BusAdapter,
    MessageBus,
    get_default_bus,
    reset_default_bus,
)
from llmwikify.apps.chat.channels.websocket import (
    WebSocketManager,
    WSClientMsg,
    WSServerMsg,
    WsSessionMap,
    _Connection,
    _handle_client_msg,
    _register_websocket_routes,
    _run_ws_chat,
    get_default_ws_session_map,
    reset_default_ws_manager,
    reset_default_ws_session_map,
)

# ── WsSessionMap unit tests ───────────────────────────────────────


class TestWsSessionMap:
    def test_empty(self) -> None:
        m = WsSessionMap()
        assert m.get("c1") is None
        assert m.stats() == {"tracked_chats": 0}

    def test_set_and_get(self) -> None:
        m = WsSessionMap()
        m.set("c1", "sess-A")
        assert m.get("c1") == "sess-A"
        assert m.stats() == {"tracked_chats": 1}

    def test_set_overwrites(self) -> None:
        m = WsSessionMap()
        m.set("c1", "sess-A")
        m.set("c1", "sess-B")
        assert m.get("c1") == "sess-B"

    def test_discard_removes(self) -> None:
        m = WsSessionMap()
        m.set("c1", "sess-A")
        m.discard("c1")
        assert m.get("c1") is None
        # Idempotent
        m.discard("c1")
        assert m.get("c1") is None

    def test_default_singleton_lazy(self) -> None:
        reset_default_ws_session_map()
        m1 = get_default_ws_session_map()
        m2 = get_default_ws_session_map()
        assert m1 is m2

    def test_reset_clears(self) -> None:
        m1 = get_default_ws_session_map()
        m1.set("c1", "sess-A")
        m2 = reset_default_ws_session_map()
        assert m2 is not m1
        assert m2.get("c1") is None


# ── _handle_client_msg with orchestrator: routing + bus + fan-out ─


class _FakeOrchestrator:
    """Async-iterable stub mimicking ChatOrchestrator.chat()."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self._events = events or []
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self, *, message: str, session_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls.append({
            "message": message,
            "session_id": session_id,
            **kwargs,
        })
        for ev in self._events:
            yield ev


def _make_conn(peer: str = "test:0") -> _Connection:
    """Build a _Connection with a real out_queue for assertion."""
    return _Connection(
        ws=None,  # type: ignore[arg-type]
        peer=peer,
        out_queue=asyncio.Queue(),
    )


async def _drain_queue(q: asyncio.Queue, n: int = 100) -> list[dict]:
    """Drain up to n messages from a queue, returning what we got."""
    out = []
    for _ in range(n):
        try:
            msg = await asyncio.wait_for(q.get(), timeout=0.5)
            out.append(msg)
        except asyncio.TimeoutError:
            break
    return out


class TestHandleMessageRoutesToOrchestrator:
    @pytest.mark.asyncio
    async def test_message_calls_orchestrator_chat(self) -> None:
        orch = _FakeOrchestrator(events=[
            {"type": "message_delta", "content": "hi"},
            {"type": "done", "content": "bye"},
        ])
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::1")
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {
                "type": WSClientMsg.MESSAGE,
                "chat_id": "chat::1",
                "content": "hello",
            },
            orchestrator=orch,
            session_map=session_map,
        )
        # The handler spawns a task; let it finish
        await asyncio.sleep(0.2)
        # Orchestrator.chat was called with the right message
        assert len(orch.calls) == 1
        assert orch.calls[0]["message"] == "hello"
        # First call has no session_id (fresh)
        assert orch.calls[0]["session_id"] is None

    @pytest.mark.asyncio
    async def test_message_fanout_uses_ws_envelope(self) -> None:
        orch = _FakeOrchestrator(events=[
            {"type": "message_delta", "content": "alpha"},
            {"type": "message_delta", "content": "beta"},
            {"type": "done", "content": "fin"},
        ])
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::1")
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {
                "type": WSClientMsg.MESSAGE,
                "chat_id": "chat::1",
                "content": "ping",
            },
            orchestrator=orch,
            session_map=session_map,
        )
        await asyncio.sleep(0.2)

        msgs = await _drain_queue(conn.out_queue, n=10)
        types = [m["type"] for m in msgs]
        # Order preserved
        assert types == ["delta", "delta", "stream_end"]
        # Translated content
        assert msgs[0]["content"] == "alpha"
        assert msgs[1]["content"] == "beta"
        assert msgs[2]["content"] == "fin"

    @pytest.mark.asyncio
    async def test_session_created_caches_session_id(self) -> None:
        orch = _FakeOrchestrator(events=[
            {"type": "session_created", "session_id": "sess-xyz"},
            {"type": "message_delta", "content": "hi"},
            {"type": "done", "content": ""},
        ])
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::A")
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {"type": WSClientMsg.MESSAGE, "chat_id": "chat::A", "content": "x"},
            orchestrator=orch,
            session_map=session_map,
        )
        await asyncio.sleep(0.2)
        # Session id cached
        assert session_map.get("chat::A") == "sess-xyz"

    @pytest.mark.asyncio
    async def test_second_message_reuses_session_id(self) -> None:
        orch = _FakeOrchestrator()
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::A")
        session_map = WsSessionMap()
        session_map.set("chat::A", "sess-prior")

        await _handle_client_msg(
            conn, manager,
            {"type": WSClientMsg.MESSAGE, "chat_id": "chat::A", "content": "y"},
            orchestrator=orch,
            session_map=session_map,
        )
        await asyncio.sleep(0.2)
        # Reused prior session_id
        assert orch.calls[0]["session_id"] == "sess-prior"

    @pytest.mark.asyncio
    async def test_message_mirrored_to_bus(self) -> None:
        bus = MessageBus()
        # Inject bus into the default adapter path by patching get_default_bus
        from llmwikify.apps.chat.bus import queue as queue_mod
        queue_mod._default = bus  # bypass lazy init

        orch = _FakeOrchestrator(events=[
            {"type": "message_delta", "content": "from-orch"},
            {"type": "done", "content": "ok"},
        ])
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::B")
        session_map = WsSessionMap()

        try:
            await _handle_client_msg(
                conn, manager,
                {
                    "type": WSClientMsg.MESSAGE,
                    "chat_id": "chat::B",
                    "content": "x",
                },
                orchestrator=orch,
                session_map=session_map,
            )
            await asyncio.sleep(0.2)
            # Drain bus
            mirrored: list = []
            for _ in range(5):
                m = await bus.consume_outbound(timeout=0.2)
                if m is None:
                    break
                mirrored.append(m)
            assert len(mirrored) >= 2
            types = [m.payload["type"] for m in mirrored]
            assert "message_delta" in types
            assert "done" in types
            # target_id is chat_id (WS-targeted)
            assert all(m.target_id == "chat::B" for m in mirrored)
        finally:
            # Restore the singleton slot so subsequent tests get a fresh
            # default bus via the lazy init path.
            queue_mod._default = None

    @pytest.mark.asyncio
    async def test_multi_conn_fanout(self) -> None:
        """Two connections on the same chat both see the orchestrator's events."""
        orch = _FakeOrchestrator(events=[
            {"type": "message_delta", "content": "shared"},
            {"type": "done", "content": ""},
        ])
        conn1 = _make_conn("c1:0")
        conn2 = _make_conn("c2:0")
        manager = WebSocketManager()
        manager.attach(conn1, "chat::F")
        manager.attach(conn2, "chat::F")
        session_map = WsSessionMap()

        # Use conn1 to send the message; conn2 should also receive
        await _handle_client_msg(
            conn1, manager,
            {"type": WSClientMsg.MESSAGE, "chat_id": "chat::F", "content": "x"},
            orchestrator=orch,
            session_map=session_map,
        )
        await asyncio.sleep(0.2)
        msgs1 = await _drain_queue(conn1.out_queue, n=5)
        msgs2 = await _drain_queue(conn2.out_queue, n=5)
        assert [m["type"] for m in msgs1] == ["delta", "stream_end"]
        assert [m["type"] for m in msgs2] == ["delta", "stream_end"]
        assert msgs1[0]["content"] == "shared"
        assert msgs2[0]["content"] == "shared"


# ── Error handling ────────────────────────────────────────────────


class TestHandleMessageErrorPath:
    @pytest.mark.asyncio
    async def test_orchestrator_exception_fans_out_error(self) -> None:
        class _BoomOrch:
            async def chat(self, **kwargs: Any) -> Any:
                raise RuntimeError("synthetic orchestrator failure")
                yield  # noqa: F841 — make this a generator

        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::E")
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {"type": WSClientMsg.MESSAGE, "chat_id": "chat::E", "content": "x"},
            orchestrator=_BoomOrch(),
            session_map=session_map,
        )
        await asyncio.sleep(0.2)
        msgs = await _drain_queue(conn.out_queue, n=5)
        # At least one error envelope was emitted
        error_msgs = [m for m in msgs if m.get("type") == WSServerMsg.ERROR]
        assert len(error_msgs) >= 1
        assert "Internal error" in error_msgs[0]["error"]

    @pytest.mark.asyncio
    async def test_missing_chat_id_error_backward_compat(self) -> None:
        """Even with orchestrator injected, missing chat_id still emits error."""
        orch = _FakeOrchestrator()
        conn = _make_conn()
        manager = WebSocketManager()
        # Note: NOT attaching to any chat
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {"type": WSClientMsg.MESSAGE, "chat_id": "chat::X", "content": "x"},
            orchestrator=orch,
            session_map=session_map,
        )
        # No orchestrator call should have happened
        await asyncio.sleep(0.1)
        assert orch.calls == []
        msgs = await _drain_queue(conn.out_queue, n=2)
        assert any(m.get("type") == WSServerMsg.ERROR for m in msgs)


# ── Echo fallback (dev mode, no orchestrator) ────────────────────


class TestHandleMessageEchoFallback:
    @pytest.mark.asyncio
    async def test_no_orchestrator_echoes(self) -> None:
        """When orchestrator=None, message handler falls back to Phase 14 echo."""
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::Z")
        session_map = WsSessionMap()

        await _handle_client_msg(
            conn, manager,
            {
                "type": WSClientMsg.MESSAGE,
                "chat_id": "chat::Z",
                "content": "echo me",
            },
            orchestrator=None,
            session_map=session_map,
        )
        msgs = await _drain_queue(conn.out_queue, n=5)
        types = [m["type"] for m in msgs]
        assert types == ["delta", "stream_end"]
        assert "[echo] echo me" in msgs[0]["content"]


# ── _run_ws_chat direct unit test ─────────────────────────────────


class TestRunWsChatDirect:
    @pytest.mark.asyncio
    async def test_run_ws_chat_yields_envelope_in_order(self) -> None:
        orch = _FakeOrchestrator(events=[
            {"type": "session_created", "session_id": "sess-1"},
            {"type": "message_delta", "content": "step-1"},
            {"type": "tool_call_start", "tool": "x", "args": {"a": 1}, "call_id": "c1"},
            {"type": "tool_call_end", "tool": "x", "result": "r", "call_id": "c1"},
            {"type": "done", "content": "fin"},
        ])
        conn = _make_conn()
        manager = WebSocketManager()
        manager.attach(conn, "chat::R")
        session_map = WsSessionMap()

        await _run_ws_chat(
            conn=conn, manager=manager,
            chat_id="chat::R", content="test",
            orchestrator=orch, session_map=session_map,
        )
        msgs = await _drain_queue(conn.out_queue, n=10)
        types = [m["type"] for m in msgs]
        # SSE→WS translation maps session_created→session_created (passthrough),
        # message_delta→delta, tool_call_start→tool_call (phase=start),
        # tool_call_end→tool_call (phase=end), done→stream_end
        assert types == [
            "session_created", "delta", "tool_call", "tool_call", "stream_end",
        ]
        # session_id was captured by WsSessionMap
        assert session_map.get("chat::R") == "sess-1"
        # tool_call envelope has phase + tool
        tool_msgs = [m for m in msgs if m["type"] == "tool_call"]
        assert tool_msgs[0]["phase"] == "start"
        assert tool_msgs[0]["tool"] == "x"
        assert tool_msgs[1]["phase"] == "end"


# ── _register_websocket_routes signature compat ───────────────────


class TestRegisterRoutesSignature:
    def test_accepts_legacy_no_chat_service(self) -> None:
        """Calling _register_websocket_routes without chat_service
        should NOT raise (backward compat for tests / dev mode)."""
        from fastapi import FastAPI
        app = FastAPI()
        # Should not raise
        _register_websocket_routes(app, api_key="")

    def test_accepts_chat_service_param(self) -> None:
        from fastapi import FastAPI
        app = FastAPI()
        _register_websocket_routes(
            app, api_key="", chat_service=None,
        )

    def test_accepts_orchestrator_directly(self) -> None:
        """If chat_service is a raw ChatOrchestrator (no .chat_service),
        we should still resolve to it (via getattr fallback)."""
        from fastapi import FastAPI
        app = FastAPI()
        orch = _FakeOrchestrator()
        _register_websocket_routes(
            app, api_key="", chat_service=orch,
        )
        # The internal ``orchestrator`` should resolve to the orch directly
        # (verified by checking the closure was created without error)
