"""Phase 13 — MessageBus: in-process pub/sub (borrowed from nanobot v0.2.1).

借鉴 nanobot v0.2.1 ``nanobot/bus/queue.py`` 的双 ``asyncio.Queue`` 设计：

  - ``_inbound_q: asyncio.Queue[InboundMessage]`` — channel → runner
  - ``_outbound_q: asyncio.Queue[OutboundMessage]`` — runner → channel

设计目标：

  - **解耦 ChatOrchestrator ↔ ChatRunnerV2 ↔ DreamScheduler ↔ AutoCompact**
    当前直接调用的紧耦合。Phase 13 仅铺路；后续可逐步迁移。
  - **零侵入缺省行为** — ``get_default_bus()`` 永远返回一个可用的 bus，
    即使没有调用方 publish，``consume_*`` 也只是 timeout 返回。
  - **可观测性** — ``stats()`` 返回 publish/consume 计数 + 当前 queue size，
    便于 `/api/health` 加 bus metrics。
  - **可替换** — 测试可注入 mock bus；生产可用 redis-bus 等替换。
  - **同进程** — Phase 13 仅支持同进程。多进程 / Redis 由 Phase 15+ 处理。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

from llmwikify.apps.chat.bus.events import (
    ALL_OUTBOUND_META,
    InboundMessage,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class MessageBus:
    """In-process async pub/sub for chat/agent messages.

    Mirrors the lifecycle of ``nanobot/bus/queue.py``:

      - ``publish_inbound(msg)`` — non-blocking enqueue; never raises
        on a full queue (drops oldest in dev, logs warning).
      - ``consume_inbound(timeout=None)`` — async; returns InboundMessage
        or None on timeout.
      - ``publish_outbound(msg)`` / ``consume_outbound(...)`` — symmetric.
      - ``stats()`` — counters for /api/health introspection.
      - ``reset()`` — clear queues + counters; tests only.
    """

    # Inbound queue grows unbounded (we don't want to drop user input).
    # Outbound queue is bounded because channels can be slow; full
    # outbound queue is a real signal (channel backpressure).
    DEFAULT_OUTBOUND_MAXSIZE = 1024

    def __init__(self, *, outbound_maxsize: int | None = None) -> None:
        self._inbound_q: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound_q: asyncio.Queue[OutboundMessage] = asyncio.Queue(
            maxsize=outbound_maxsize or self.DEFAULT_OUTBOUND_MAXSIZE,
        )
        # Counters (monotonic)
        self._inbound_published = 0
        self._inbound_consumed = 0
        self._outbound_published = 0
        self._outbound_consumed = 0
        self._outbound_dropped = 0

    # ── inbound ────────────────────────────────────────────────

    def publish_inbound(self, msg: InboundMessage) -> None:
        """Enqueue an inbound message. Non-blocking; never raises."""
        self._inbound_q.put_nowait(msg)
        self._inbound_published += 1

    async def consume_inbound(
        self, timeout: float | None = None
    ) -> InboundMessage | None:
        """Dequeue the next inbound message.

        Returns ``None`` if *timeout* (seconds) elapses with no message.
        Passing ``timeout=None`` waits forever.
        """
        if timeout is None:
            msg = await self._inbound_q.get()
        else:
            try:
                msg = await asyncio.wait_for(
                    self._inbound_q.get(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                return None
        self._inbound_consumed += 1
        return msg

    def inbound_size(self) -> int:
        return self._inbound_q.qsize()

    # ── outbound ───────────────────────────────────────────────

    def publish_outbound(self, msg: OutboundMessage) -> bool:
        """Enqueue an outbound message. Returns ``False`` if dropped.

        A drop happens when the outbound queue is full (channel is
        slow). The caller decides whether to drop silently, buffer
        somewhere else, or raise.
        """
        try:
            self._outbound_q.put_nowait(msg)
        except asyncio.QueueFull:
            self._outbound_dropped += 1
            logger.warning(
                "MessageBus: outbound queue full, dropped message "
                "(target=%s session=%s)",
                msg.target_id, msg.session_key,
            )
            return False
        self._outbound_published += 1
        return True

    async def consume_outbound(
        self, timeout: float | None = None
    ) -> OutboundMessage | None:
        """Dequeue the next outbound message.

        Returns ``None`` on timeout. Passing ``timeout=None`` waits
        forever.
        """
        if timeout is None:
            msg = await self._outbound_q.get()
        else:
            try:
                msg = await asyncio.wait_for(
                    self._outbound_q.get(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                return None
        self._outbound_consumed += 1
        return msg

    def outbound_size(self) -> int:
        return self._outbound_q.qsize()

    # ── introspection ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return bus counters + queue sizes for ``/api/health`` etc."""
        return {
            "inbound": {
                "published": self._inbound_published,
                "consumed": self._inbound_consumed,
                "queued": self.inbound_size(),
            },
            "outbound": {
                "published": self._outbound_published,
                "consumed": self._outbound_consumed,
                "dropped": self._outbound_dropped,
                "queued": self.outbound_size(),
                "maxsize": self._outbound_q.maxsize,
            },
        }

    # ── lifecycle ──────────────────────────────────────────────

    def reset(self) -> None:
        """Clear queues + counters. Tests only.

        Drains whatever's pending without yielding it. Production code
        should let queues drain naturally on shutdown.
        """
        while not self._inbound_q.empty():
            try:
                self._inbound_q.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self._outbound_q.empty():
            try:
                self._outbound_q.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._inbound_published = 0
        self._inbound_consumed = 0
        self._outbound_published = 0
        self._outbound_consumed = 0
        self._outbound_dropped = 0


# ── Default singleton ────────────────────────────────────────────


_default: MessageBus | None = None
_default_lock: Any = None  # lazy import to keep this module sync-importable


def _get_default_lock() -> Any:
    global _default_lock
    if _default_lock is None:
        import threading

        _default_lock = threading.Lock()
    return _default_lock


def get_default_bus() -> MessageBus:
    """Return the process-wide default ``MessageBus``.

    Lazy-initialized and cached. Tests that need isolation should
    construct their own ``MessageBus()`` instance (or call
    ``reset_default_bus()``).
    """
    global _default
    with _get_default_lock():
        if _default is None:
            _default = MessageBus()
        return _default


def reset_default_bus() -> MessageBus:
    """Force-replace the default bus with a fresh one. Returns it.

    Use only in test setup/teardown.
    """
    global _default
    with _get_default_lock():
        _default = MessageBus()
        return _default


def set_default_bus(bus: MessageBus | None) -> None:
    """Replace the default bus singleton. Pass ``None`` to clear.

    Production code should call this in startup with a configured bus
    (e.g. with custom ``outbound_maxsize``). Tests use ``reset_default_bus()``.
    """
    global _default
    with _get_default_lock():
        _default = bus


__all__ = [
    "MessageBus",
    "get_default_bus",
    "reset_default_bus",
    "set_default_bus",
]
