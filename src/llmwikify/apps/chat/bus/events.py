"""Phase 13 — Message bus event types (borrowed from nanobot v0.2.1).

借鉴 nanobot v0.2.1 ``nanobot/bus/events.py`` 的 ``InboundMessage`` /
``OutboundMessage`` 双消息类型 + 显式 metadata 键（``OUTBOUND_META_*``
/ ``INBOUND_META_*``）设计。

设计目标：

  - **不可变 dataclass** + ``to_dict()`` / ``from_dict()`` 双向序列化，
    让 bus 消息可 JSON 化（未来 WebSocket 透传）。
  - **显式 metadata** 而不是把控制信号塞进 ``content`` / ``type`` 字段，
    方便 ChatOrchestrator / DreamScheduler / WebSocket handler 解耦识别。
  - **向后兼容 SSE 契约** — ``payload`` 字段就是 ``ChatEvent`` factory 输出
    的 dict，所以现有 ``yield event`` 路径可以直接 ``publish_outbound``，
    无须改 SSE 客户端契约。
  - **与现有 ``ChatOrchestrator`` 解耦** — ChatOrchestrator 不直接持有 bus，
    bus 通过 ``set_default_bus(bus)`` 注入；不传则 use ``null_bus``（singleton），
    现有 SSE 路径完全无感。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# ─── Special metadata keys ───────────────────────────────────────
#
# Mirrors nanobot v0.2.1 ``bus/events.py:OUTBOUND_META_AGENT_UI`` etc.
# Names are namespaced under ``_meta_`` so they never collide with
# user-authored payload fields.
#
# Inbound (from channel → runner):
#   - ``INBOUND_META_RUNTIME_CONTROL`` — bus-level control (e.g. ``/stop``
#     injected from cron or subagent), LLM must not see as user turn
#   - ``INBOUND_META_RESUMED``         — session was resumed mid-turn
#                                      (after crash recovery)
# Outbound (from runner → channel):
#   - ``OUTBOUND_META_STREAM_DELTA``   — incremental token chunk
#   - ``OUTBOUND_META_STREAM_END``     — stream finished, no more deltas
#   - ``OUTBOUND_META_STREAM_ID``      — multi-segment concurrent streams
#   - ``OUTBOUND_META_PROGRESS``       — non-content progress (e.g. tool
#                                      hint) — usually filtered by channel
#   - ``OUTBOUND_META_RETRY_WAIT``     — retry-in-progress, channel may
#                                      render a spinner
#   - ``OUTBOUND_META_WANTS_STREAM``   — capability: channel supports
#                                      streaming

INBOUND_META_RUNTIME_CONTROL = "_meta_runtime_control"
INBOUND_META_RESUMED = "_meta_resumed"

OUTBOUND_META_STREAM_DELTA = "_meta_stream_delta"
OUTBOUND_META_STREAM_END = "_meta_stream_end"
OUTBOUND_META_STREAM_ID = "_meta_stream_id"
OUTBOUND_META_PROGRESS = "_meta_progress"
OUTBOUND_META_RETRY_WAIT = "_meta_retry_wait"
OUTBOUND_META_WANTS_STREAM = "_meta_wants_stream"

ALL_OUTBOUND_META = frozenset(
    {
        OUTBOUND_META_STREAM_DELTA,
        OUTBOUND_META_STREAM_END,
        OUTBOUND_META_STREAM_ID,
        OUTBOUND_META_PROGRESS,
        OUTBOUND_META_RETRY_WAIT,
        OUTBOUND_META_WANTS_STREAM,
    }
)


# ─── Messages ────────────────────────────────────────────────────


@dataclass
class InboundMessage:
    """A message flowing **into** the chat runner (channel → runner).

    In Phase 13 this is constructed manually by ``ChatOrchestrator`` /
    ``/api/agent/chat`` HTTP handler. In Phase 14 the WebSocket
    channel will publish InboundMessage directly.

    Attributes
    ----------
    channel
        Logical channel identifier (``"http"`` / ``"websocket"`` /
        ``"system"`` / ``"cli"``).
    sender_id
        End-user identifier. For ``channel="http"`` this is the API
        key holder; for ``"websocket"`` this is the connection's
        ``chat_id``.
    content
        User-authored text. Empty when the message is purely a control
        signal (e.g. ``/stop`` broadcast).
    session_key
        Routing key (typically ``f"{channel}:{sender_id}"``). Used by
        SessionManager to scope persistence + locks.
    metadata
        Free-form dict. Namespaced control signals use ``_meta_*``
        keys (see module-level constants).
    timestamp
        Unix epoch seconds (float). Used for ordering + RTT metrics.
    message_id
        Optional client-supplied id for echo / dedup.
    """

    channel: str = "http"
    sender_id: str = ""
    content: str = ""
    session_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: time.time())
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "sender_id": self.sender_id,
            "content": self.content,
            "session_key": self.session_key,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
            "message_id": self.message_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InboundMessage:
        return cls(
            channel=data.get("channel", "http"),
            sender_id=data.get("sender_id", ""),
            content=data.get("content", ""),
            session_key=data.get("session_key", ""),
            metadata=dict(data.get("metadata") or {}),
            timestamp=float(data.get("timestamp") or time.time()),
            message_id=data.get("message_id") or uuid.uuid4().hex[:12],
        )


@dataclass
class OutboundMessage:
    """A message flowing **out of** the chat runner (runner → channel).

    Attributes
    ----------
    channel
        Target channel (``"http"`` / ``"websocket"`` / ``"system"``).
        If ``""``, any channel may consume (fan-out).
    target_id
        Destination identifier (per-channel). For ``channel="http"`` this
        is the SSE connection id; for ``"websocket"`` this is the
        ``chat_id``.
    session_key
        Echoed routing key for the consuming channel.
    payload
        The actual SSE event dict (what ``ChatOrchestrator`` currently
        yields). Same shape across all channels.
    metadata
        Free-form dict. Namespaced control signals use ``_meta_*``
        keys.
    timestamp
        Unix epoch seconds (float).
    """

    channel: str = ""
    target_id: str = ""
    session_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "target_id": self.target_id,
            "session_key": self.session_key,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutboundMessage:
        return cls(
            channel=data.get("channel", ""),
            target_id=data.get("target_id", ""),
            session_key=data.get("session_key", ""),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or {}),
            timestamp=float(data.get("timestamp") or time.time()),
        )

    @property
    def is_stream_delta(self) -> bool:
        """True iff this message carries a streaming content delta."""
        return bool(self.metadata.get(OUTBOUND_META_STREAM_DELTA))

    @property
    def is_stream_end(self) -> bool:
        """True iff this message marks the end of a streaming segment."""
        return bool(self.metadata.get(OUTBOUND_META_STREAM_END))


__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "INBOUND_META_RUNTIME_CONTROL",
    "INBOUND_META_RESUMED",
    "OUTBOUND_META_STREAM_DELTA",
    "OUTBOUND_META_STREAM_END",
    "OUTBOUND_META_STREAM_ID",
    "OUTBOUND_META_PROGRESS",
    "OUTBOUND_META_RETRY_WAIT",
    "OUTBOUND_META_WANTS_STREAM",
    "ALL_OUTBOUND_META",
]
