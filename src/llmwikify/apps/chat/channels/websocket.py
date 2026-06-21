"""Phase 14 — WebSocket agent channel (borrowed from nanobot v0.2.1).

借鉴 nanobot v0.2.1 ``nanobot/channels/websocket.py`` 核心 50%：

  - **token_issue 协议** — 静态 ``?token=<api_key>`` 握手（HMAC 简化版：直接比对），
    客户端连接时验证；也可临时 token（Phase 15+）
  - **订阅模型** — ``_subs: dict[chat_id, set[connection]]`` + 反向索引
    ``_conn_chats: dict[connection, set[chat_id]]`` 维护 O(1) cleanup
  - **客户端 envelope** — 客户端发 ``{type: "new_chat"|"attach"|"message"|"ping"}``；
    服务端发 ``{type: "ready"|"attached"|"chat_created"|"delta"|"stream_end"|"pong"|"error"}``
  - **outbound per-conn queue** — Phase 14 内置，Phase 15+ 改为从 MessageBus consume_outbound

设计原则：

  - **渐进式** — Phase 14 只把"通道 + 协议 + 订阅"打通，**不接** ChatOrchestrator。
    Phase 15+ 让 ChatOrchestrator 把 SSE ``yield event`` 改 ``publish_outbound``，
    然后 WS handler 从 bus 拉取 fan-out。本期 handler 内置 send_event 接口供测试。
  - **fastapi native** — 用 fastapi.WebSocket（已确认 0.135.1 支持），不引入新依赖。
  - **认证可关** — token 不匹配 → close code 1008（policy violation）。生产用
    WikiServer 的 api_key 校验（与 REST API 一致）。

限制（本期）：

  - 单 process。Redis-bus / 多实例由 Phase 15+ 处理。
  - 无 reconnect 状态恢复（客户端断线后丢失 in-flight 消息）。
  - 不支持 multipart 上传（图片/PDF），那是 OpenAI-compat API 的范围。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, Query, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)


# ─── Server → client message types ──────────────────────────────


class WSServerMsg:
    """Server → client message type constants."""

    READY = "ready"
    ATTACHED = "attached"
    CHAT_CREATED = "chat_created"
    DELTA = "delta"
    STREAM_END = "stream_end"
    PONG = "pong"
    ERROR = "error"


# ─── Client → server message types ──────────────────────────────


class WSClientMsg:
    """Client → server message type constants."""

    NEW_CHAT = "new_chat"
    ATTACH = "attach"
    MESSAGE = "message"
    PING = "ping"


# ─── Connection bookkeeping ─────────────────────────────────────


@dataclass(eq=False)
class _Connection:
    """Per-connection state held by the WebSocketManager.

    ``eq=False`` makes the dataclass use ``id(self)`` for hashing so it
    can be a dict key / set member. We never compare two ``_Connection``
    instances by value — identity is the only thing that matters
    for the manager's indexes.

    Attributes
    ----------
    ws
        The fastapi WebSocket instance (live for the duration of the
        connection).
    peer
        ``"{client_host}:{client_port}"`` for logging / debugging.
    subscribed_chats
        Set of chat_ids this connection has subscribed to. Used both
        for fan-out lookup and for cleanup when the connection closes.
    out_queue
        ``asyncio.Queue`` of pending server → client messages. We
        push from the manager side and ``await`` on the WebSocket
        send side, so a single connection never blocks the manager's
        publish path on slow peers.
    closed
        ``True`` once the WebSocket close handshake completed. The
        manager checks this before pushing to avoid sending to a
        dead socket.
    connected_at
        Unix timestamp when the connection was established.
    """

    ws: WebSocket
    peer: str
    subscribed_chats: set[str] = field(default_factory=set)
    out_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue,
    )
    closed: bool = False
    connected_at: float = field(default_factory=time.time)


class WebSocketManager:
    """Fan-out hub for the WebSocket channel.

    Three indexes (see borrow note at top):

      - ``_subs[chat_id] -> set[_Connection]`` — for ``send_to_chat``
      - ``_conn_chats[connection] -> set[chat_id]`` — for O(1) cleanup
        on disconnect (mirror of subscribed_chats, indexed at manager
        level for the iteration case)

    Thread-safety: all public methods must be called from a single
    asyncio event loop. We don't use locks because asyncio doesn't
    preempt between awaits in the same task.
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[_Connection]] = defaultdict(set)
        self._conn_chats: dict[_Connection, set[str]] = defaultdict(set)

    # ── subscription ─────────────────────────────────────────

    def attach(self, conn: _Connection, chat_id: str) -> None:
        """Subscribe a connection to a chat_id."""
        if chat_id in conn.subscribed_chats:
            return
        conn.subscribed_chats.add(chat_id)
        self._subs[chat_id].add(conn)
        self._conn_chats[conn].add(chat_id)

    def detach(self, conn: _Connection, chat_id: str) -> None:
        """Unsubscribe a connection from a chat_id (idempotent)."""
        if chat_id not in conn.subscribed_chats:
            return
        conn.subscribed_chats.discard(chat_id)
        self._subs[chat_id].discard(conn)
        # ``self._conn_chats[conn].discard`` is a no-op on a
        # ``defaultdict`` if the key was already absent — but we
        # need to actually delete the entry when it becomes empty,
        # otherwise ``total_connections()`` over-reports.
        self._conn_chats[conn].discard(chat_id)
        if not self._conn_chats[conn]:
            del self._conn_chats[conn]
        if not self._subs[chat_id]:
            del self._subs[chat_id]

    def detach_all(self, conn: _Connection) -> None:
        """Unsubscribe a connection from all chat_ids (on disconnect)."""
        for chat_id in list(self._conn_chats.get(conn, set())):
            self.detach(conn, chat_id)
        # ``detach`` deletes the entry when empty, but make sure we
        # don't leave a phantom empty entry behind.
        if conn in self._conn_chats:
            del self._conn_chats[conn]

    # ── fan-out ──────────────────────────────────────────────

    def subscribed_count(self, chat_id: str) -> int:
        return len(self._subs.get(chat_id, set()))

    def total_connections(self) -> int:
        return len(self._conn_chats)

    async def send_to_chat(
        self, chat_id: str, msg: dict[str, Any]
    ) -> int:
        """Send a message to all connections subscribed to ``chat_id``.

        Returns the number of connections the message was enqueued for.
        A returned count of 0 means no one is listening (yet).
        Connections whose ``closed`` flag is True are silently skipped.
        """
        count = 0
        for conn in list(self._subs.get(chat_id, set())):
            if conn.closed:
                continue
            try:
                conn.out_queue.put_nowait(msg)
                count += 1
            except asyncio.QueueFull:
                # Per-conn queue full: this peer is slow. Drop + log
                # but don't crash the whole fan-out.
                logger.warning(
                    "WebSocket peer %s queue full, dropping msg to chat %s",
                    conn.peer, chat_id,
                )
        return count

    # ── metrics ──────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "connections": self.total_connections(),
            "chats": len(self._subs),
            "subscriptions_per_chat": {
                chat_id: len(s) for chat_id, s in self._subs.items()
            },
        }


# ─── Singleton manager (mirrors MessageBus pattern) ─────────────


_default: WebSocketManager | None = None
_default_lock: Any = None


def _get_default_lock() -> Any:
    global _default_lock
    if _default_lock is None:
        import threading
        _default_lock = threading.Lock()
    return _default_lock


def get_default_ws_manager() -> WebSocketManager:
    """Return the process-wide default ``WebSocketManager``."""
    global _default
    with _get_default_lock():
        if _default is None:
            _default = WebSocketManager()
        return _default


def reset_default_ws_manager() -> WebSocketManager:
    """Force-replace the default manager. Tests only."""
    global _default
    with _get_default_lock():
        _default = WebSocketManager()
        return _default


def set_default_ws_manager(mgr: WebSocketManager | None) -> None:
    """Replace the default manager. ``None`` clears."""
    global _default
    with _get_default_lock():
        _default = mgr


# ─── Outbound queue size (per-connection, used to bound drops) ──


PER_CONN_OUT_MAXSIZE = 256


# ─── FastAPI router ─────────────────────────────────────────────


def _register_websocket_routes(
    app: FastAPI, *, api_key: str = "",
) -> None:
    """Mount the WebSocket routes onto ``app``.

    Endpoints
    ---------
    WS  /api/ws/agent
        Main agent channel. Auth via ``?token=<api_key>`` query param.
        Server pushes ``ready`` on accept; client may ``new_chat`` /
        ``attach`` / ``message`` / ``ping`` thereafter.
    POST /api/ws/token
        Issue a temporary single-use token (HTTP/1.1). Currently
        a no-op shim returning a deterministic token; Phase 15+
        will plug in HMAC + TTL.

    Notes
    -----
    The ``api_key`` parameter is matched against the WikiServer's
    configured API key. When empty (default), auth is skipped —
    useful for tests and local dev. Production should always
    set ``api_key``.
    """
    router = APIRouter(tags=["websocket"])

    @router.websocket("/api/ws/agent")
    async def ws_agent(
        websocket: WebSocket,
        token: str = Query("", description="API key"),
    ) -> None:
        # Auth: simple equality check. Production deployments
        # should also enforce TLS / origin allow-listing at the
        # reverse-proxy layer.
        if api_key and token != api_key:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token",
            )
            return
        await websocket.accept()
        client = websocket.client
        peer = (
            f"{client.host}:{client.port}" if client else "unknown"
        )
        conn = _Connection(
            ws=websocket,
            peer=peer,
            out_queue=asyncio.Queue(maxsize=PER_CONN_OUT_MAXSIZE),
        )
        manager = get_default_ws_manager()
        # Greet the client
        await conn.out_queue.put({
            "type": WSServerMsg.READY,
            "peer": peer,
            "server_time": time.time(),
        })
        # Spawn the writer task (drains out_queue → ws.send_json)
        writer_task = asyncio.create_task(_writer_loop(conn))
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError as e:
                    await conn.out_queue.put({
                        "type": WSServerMsg.ERROR,
                        "error": f"Invalid JSON: {e}",
                    })
                    continue
                await _handle_client_msg(conn, manager, msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WebSocket error for peer %s", peer)
        finally:
            conn.closed = True
            manager.detach_all(conn)
            writer_task.cancel()
            try:
                await writer_task
            except (asyncio.CancelledError, Exception):
                pass

    @router.post("/api/ws/token")
    async def issue_token(
        token: str = Query("", description="API key"),
    ) -> dict[str, Any]:
        """Issue a temporary single-use token.

        Phase 14 shim: returns the same token the caller already
        presented (after auth). Phase 15+ will mint HMAC-signed
        tokens with TTL and a single-use nonce table.
        """
        if api_key and token != api_key:
            return {"error": "Unauthorized", "status_code": 401}
        # Echo the validated token back; client reuses it as
        # ``?token=...`` on the WS handshake.
        return {
            "token": token or "no-auth-dev-mode",
            "expires_in": 300,
            "single_use": False,
            "note": (
                "Phase 14 shim — TTL/single-use not yet enforced. "
                "See apply-plan §14 for the rollout plan."
            ),
        }

    app.include_router(router)


# ─── Internal helpers ───────────────────────────────────────────


async def _handle_client_msg(
    conn: _Connection,
    manager: WebSocketManager,
    msg: dict[str, Any],
) -> None:
    """Dispatch a single client message.

    Recognized client envelopes
    ---------------------------
    ``{type: "new_chat"}`` → mint a chat_id, attach, return ``chat_created``
    ``{type: "attach", chat_id: ...}`` → subscribe to existing chat_id
    ``{type: "message", chat_id: ..., content: ...}`` → echo as a stub
        ``delta`` + ``stream_end`` (Phase 14 has no ChatOrchestrator
        integration; the echo proves the message round-tripped).
    ``{type: "ping"}`` → respond with ``pong``
    """
    mtype = msg.get("type", "")
    if mtype == WSClientMsg.PING:
        await conn.out_queue.put({"type": WSServerMsg.PONG, "ts": time.time()})
        return

    if mtype == WSClientMsg.NEW_CHAT:
        chat_id = msg.get("chat_id") or f"chat::{uuid.uuid4().hex[:8]}"
        manager.attach(conn, chat_id)
        await conn.out_queue.put({
            "type": WSServerMsg.CHAT_CREATED,
            "chat_id": chat_id,
        })
        return

    if mtype == WSClientMsg.ATTACH:
        chat_id = msg.get("chat_id", "")
        if not chat_id:
            await conn.out_queue.put({
                "type": WSServerMsg.ERROR,
                "error": "attach requires chat_id",
            })
            return
        manager.attach(conn, chat_id)
        await conn.out_queue.put({
            "type": WSServerMsg.ATTACHED,
            "chat_id": chat_id,
            "subscribed_count": manager.subscribed_count(chat_id),
        })
        return

    if mtype == WSClientMsg.MESSAGE:
        chat_id = msg.get("chat_id", "")
        content = msg.get("content", "")
        if not chat_id or chat_id not in conn.subscribed_chats:
            await conn.out_queue.put({
                "type": WSServerMsg.ERROR,
                "error": "message requires chat_id (must be attached first)",
            })
            return
        # Phase 14 echo: prove the channel round-trip. Phase 15+
        # will route to ChatOrchestrator.chat() and stream the
        # real response via ``send_to_chat``.
        await manager.send_to_chat(chat_id, {
            "type": WSServerMsg.DELTA,
            "chat_id": chat_id,
            "content": f"[echo] {content}",
            "ts": time.time(),
        })
        await manager.send_to_chat(chat_id, {
            "type": WSServerMsg.STREAM_END,
            "chat_id": chat_id,
            "ts": time.time(),
        })
        return

    # Unknown message type — error back
    await conn.out_queue.put({
        "type": WSServerMsg.ERROR,
        "error": f"Unknown message type: {mtype!r}",
    })


async def _writer_loop(conn: _Connection) -> None:
    """Drain ``conn.out_queue`` into ``conn.ws.send_json``.

    Runs as a separate task so the manager's ``send_to_chat`` path
    can ``put_nowait`` without awaiting the actual WebSocket send
    (which would block on slow peers).
    """
    try:
        while not conn.closed:
            try:
                msg = await conn.out_queue.get()
            except asyncio.CancelledError:
                break
            if conn.closed:
                break
            try:
                await conn.ws.send_json(msg)
            except Exception:
                # Peer is gone; mark closed so producer side stops
                conn.closed = True
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("WebSocket writer loop crashed for %s", conn.peer)


__all__ = [
    "WebSocketManager",
    "WSServerMsg",
    "WSClientMsg",
    "get_default_ws_manager",
    "reset_default_ws_manager",
    "set_default_ws_manager",
    "_register_websocket_routes",
]
