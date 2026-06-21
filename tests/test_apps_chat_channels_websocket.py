"""Phase 14 — WebSocket agent channel tests (borrowed from nanobot v0.2.1).

Covers:
  - WebSocketManager subscription model + fan-out
  - Per-connection out_queue backpressure
  - FastAPI WS endpoint via TestClient
  - Token auth (valid / invalid)
  - Client envelopes (new_chat / attach / message / ping)
  - cleanup on disconnect
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmwikify.apps.chat.channels.websocket import (
    WebSocketManager,
    WSClientMsg,
    WSServerMsg,
    _Connection,
    _register_websocket_routes,
    get_default_ws_manager,
    reset_default_ws_manager,
    set_default_ws_manager,
)

# ── WebSocketManager unit tests ─────────────────────────────────


class TestWebSocketManager:
    def test_empty_manager(self) -> None:
        mgr = WebSocketManager()
        s = mgr.stats()
        assert s["connections"] == 0
        assert s["chats"] == 0
        assert s["subscriptions_per_chat"] == {}

    def test_attach_adds_to_both_indexes(self) -> None:
        mgr = WebSocketManager()
        # Fake connection (no actual WebSocket needed for unit tests)
        conn = _Connection(ws=None, peer="t:1")
        mgr.attach(conn, "chat-A")
        assert "chat-A" in conn.subscribed_chats
        assert conn in mgr._subs["chat-A"]
        assert "chat-A" in mgr._conn_chats[conn]

    def test_attach_idempotent(self) -> None:
        mgr = WebSocketManager()
        conn = _Connection(ws=None, peer="t:1")
        mgr.attach(conn, "chat-A")
        mgr.attach(conn, "chat-A")
        assert mgr.subscribed_count("chat-A") == 1

    def test_detach_removes_from_both_indexes(self) -> None:
        mgr = WebSocketManager()
        conn = _Connection(ws=None, peer="t:1")
        mgr.attach(conn, "chat-A")
        mgr.detach(conn, "chat-A")
        assert mgr.subscribed_count("chat-A") == 0
        assert conn not in mgr._conn_chats

    def test_detach_idempotent(self) -> None:
        mgr = WebSocketManager()
        conn = _Connection(ws=None, peer="t:1")
        mgr.detach(conn, "chat-A")  # no-op

    def test_detach_all(self) -> None:
        mgr = WebSocketManager()
        conn = _Connection(ws=None, peer="t:1")
        mgr.attach(conn, "chat-A")
        mgr.attach(conn, "chat-B")
        mgr.detach_all(conn)
        assert mgr.stats() == {
            "connections": 0,
            "chats": 0,
            "subscriptions_per_chat": {},
        }

    @pytest.mark.asyncio
    async def test_send_to_chat_no_subscribers(self) -> None:
        mgr = WebSocketManager()
        count = await mgr.send_to_chat("nobody-home", {"type": "x"})
        assert count == 0

    @pytest.mark.asyncio
    async def test_send_to_chat_fans_out(self) -> None:
        mgr = WebSocketManager()
        c1 = _Connection(ws=None, peer="t:1")
        c2 = _Connection(ws=None, peer="t:2")
        mgr.attach(c1, "chat-A")
        mgr.attach(c2, "chat-A")
        count = await mgr.send_to_chat("chat-A", {"type": "delta", "n": 1})
        assert count == 2
        # Both queues got the message
        m1 = await asyncio.wait_for(c1.out_queue.get(), timeout=0.1)
        m2 = await asyncio.wait_for(c2.out_queue.get(), timeout=0.1)
        assert m1["type"] == "delta"
        assert m2["type"] == "delta"

    @pytest.mark.asyncio
    async def test_send_skips_closed_connections(self) -> None:
        mgr = WebSocketManager()
        c1 = _Connection(ws=None, peer="t:1")
        c2 = _Connection(ws=None, peer="t:2")
        c2.closed = True
        mgr.attach(c1, "chat-A")
        mgr.attach(c2, "chat-A")
        count = await mgr.send_to_chat("chat-A", {"type": "delta"})
        assert count == 1  # c2 skipped

    @pytest.mark.asyncio
    async def test_backpressure_drops_when_queue_full(self) -> None:
        """When the per-conn out_queue is full, the dropped msg
        is NOT counted toward ``send_to_chat``'s return value."""
        mgr = WebSocketManager()
        conn = _Connection(ws=None, peer="t:1")
        conn.out_queue = asyncio.Queue(maxsize=2)
        mgr.attach(conn, "chat-A")
        # First two succeed
        assert await mgr.send_to_chat("chat-A", {"n": 1}) == 1
        assert await mgr.send_to_chat("chat-A", {"n": 2}) == 1
        # Third is dropped (queue full); ``send_to_chat`` returns
        # 0 because the put_nowait raised and was swallowed.
        assert await mgr.send_to_chat("chat-A", {"n": 3}) == 0
        # Queue still has only 2 messages (the first two)
        assert conn.out_queue.qsize() == 2


# ── Singleton helpers ──────────────────────────────────────────


class TestSingletonHelpers:
    def test_get_default_lazy(self) -> None:
        set_default_ws_manager(None)
        m1 = get_default_ws_manager()
        m2 = get_default_ws_manager()
        assert m1 is m2

    def test_reset_replaces(self) -> None:
        m1 = get_default_ws_manager()
        m2 = reset_default_ws_manager()
        assert m1 is not m2

    def test_set_replaces(self) -> None:
        custom = WebSocketManager()
        set_default_ws_manager(custom)
        assert get_default_ws_manager() is custom
        set_default_ws_manager(None)


# ── FastAPI WS endpoint integration ─────────────────────────────


class TestWebSocketEndpoint:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = FastAPI()
        _register_websocket_routes(app, api_key="")
        reset_default_ws_manager()
        return app

    @pytest.fixture
    def app_with_auth(self) -> FastAPI:
        app = FastAPI()
        _register_websocket_routes(app, api_key="secret123")
        reset_default_ws_manager()
        return app

    def test_invalid_token_closes_with_1008(self, app_with_auth: FastAPI) -> None:
        """When token doesn't match, server closes before accepting."""
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(app_with_auth)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/ws/agent?token=wrong"):
                pass
        assert exc.value.code == 1008

    def test_valid_token_connects(self, app_with_auth: FastAPI) -> None:
        client = TestClient(app_with_auth)
        with client.websocket_connect("/api/ws/agent?token=secret123") as ws:
            ready = ws.receive_json()
            assert ready["type"] == WSServerMsg.READY
            assert "peer" in ready
            assert "server_time" in ready

    def test_no_auth_mode(self, app: FastAPI) -> None:
        """When api_key="", the endpoint accepts without a token."""
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ready = ws.receive_json()
            assert ready["type"] == WSServerMsg.READY

    def test_ping_pong(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": WSClientMsg.PING})
            pong = ws.receive_json()
            assert pong["type"] == WSServerMsg.PONG
            assert "ts" in pong

    def test_new_chat_returns_chat_id(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": WSClientMsg.NEW_CHAT})
            created = ws.receive_json()
            assert created["type"] == WSServerMsg.CHAT_CREATED
            assert created["chat_id"].startswith("chat::")

    def test_new_chat_with_provided_chat_id(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({
                "type": WSClientMsg.NEW_CHAT,
                "chat_id": "my-custom-id",
            })
            created = ws.receive_json()
            assert created["chat_id"] == "my-custom-id"

    def test_attach_to_existing_chat(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({
                "type": WSClientMsg.NEW_CHAT,
                "chat_id": "shared",
            })
            ws.receive_json()  # chat_created
            ws.send_json({
                "type": WSClientMsg.ATTACH,
                "chat_id": "shared",
            })
            attached = ws.receive_json()
            assert attached["type"] == WSServerMsg.ATTACHED
            assert attached["chat_id"] == "shared"
            assert attached["subscribed_count"] == 1

    def test_attach_without_chat_id_errors(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": WSClientMsg.ATTACH})
            err = ws.receive_json()
            assert err["type"] == WSServerMsg.ERROR
            assert "chat_id" in err["error"]

    def test_message_echo_round_trip(self, app: FastAPI) -> None:
        """A message published to a chat the connection is attached to
        comes back as a delta + stream_end (Phase 14 echo stub)."""
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({
                "type": WSClientMsg.NEW_CHAT,
                "chat_id": "echo-room",
            })
            ws.receive_json()  # chat_created
            ws.send_json({
                "type": WSClientMsg.MESSAGE,
                "chat_id": "echo-room",
                "content": "hello",
            })
            delta = ws.receive_json()
            assert delta["type"] == WSServerMsg.DELTA
            assert "[echo] hello" in delta["content"]
            end = ws.receive_json()
            assert end["type"] == WSServerMsg.STREAM_END

    def test_message_without_attach_errors(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({
                "type": WSClientMsg.MESSAGE,
                "chat_id": "unknown",
                "content": "x",
            })
            err = ws.receive_json()
            assert err["type"] == WSServerMsg.ERROR

    def test_unknown_message_type_errors(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": "what_is_this"})
            err = ws.receive_json()
            assert err["type"] == WSServerMsg.ERROR

    def test_invalid_json_errors(self, app: FastAPI) -> None:
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_text("not valid json {{{")
            err = ws.receive_json()
            assert err["type"] == WSServerMsg.ERROR
            assert "Invalid JSON" in err["error"]

    def test_disconnect_cleanup(self, app: FastAPI) -> None:
        """After disconnect, the manager should no longer track the connection."""
        manager = get_default_ws_manager()
        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": WSClientMsg.NEW_CHAT, "chat_id": "X"})
            ws.receive_json()  # chat_created
            assert manager.subscribed_count("X") == 1
        # Connection closed — manager should clean up
        # (small grace period for the writer_task to finish)
        import time as _time
        _time.sleep(0.05)
        assert manager.subscribed_count("X") == 0

    def test_token_issue_endpoint_no_auth(self, app: FastAPI) -> None:
        """When api_key="", /api/ws/token echoes dev token."""
        client = TestClient(app)
        resp = client.post("/api/ws/token")
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert "expires_in" in body

    def test_token_issue_with_valid_token(self, app_with_auth: FastAPI) -> None:
        client = TestClient(app_with_auth)
        resp = client.post("/api/ws/token?token=secret123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"] == "secret123"

    def test_token_issue_with_wrong_token(self, app_with_auth: FastAPI) -> None:
        client = TestClient(app_with_auth)
        resp = client.post("/api/ws/token?token=nope")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status_code"] == 401


# ── Multi-connection fan-out (real WS) ──────────────────────────


class TestMultiConnectionFanOut:
    def test_two_subscribers_see_same_message(self) -> None:
        """Two connections subscribed to the same chat both receive
        messages published via send_to_chat."""
        app = FastAPI()
        _register_websocket_routes(app, api_key="")
        reset_default_ws_manager()

        client = TestClient(app)
        with client.websocket_connect("/api/ws/agent") as ws1, \
             client.websocket_connect("/api/ws/agent") as ws2:
            ws1.receive_json()  # ready
            ws2.receive_json()  # ready
            # Both attach to "broadcast"
            ws1.send_json({"type": "new_chat", "chat_id": "broadcast"})
            ws1.receive_json()
            ws2.send_json({"type": "attach", "chat_id": "broadcast"})
            ws2.receive_json()
            # ws1 publishes a message → both should see delta + stream_end
            ws1.send_json({
                "type": "message",
                "chat_id": "broadcast",
                "content": "hi all",
            })
            # Both get delta then stream_end
            for ws in (ws1, ws2):
                delta = ws.receive_json()
                assert delta["type"] == "delta"
                assert "[echo] hi all" in delta["content"]
                end = ws.receive_json()
                assert end["type"] == "stream_end"
