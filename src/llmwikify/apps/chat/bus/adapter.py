"""Phase 19-A — BusAdapter: mirror SSE events to MessageBus + SSE→WS translation.

This module is the seam between the orchestrator's SSE-style ``yield event``
output and the in-process ``MessageBus`` (Phase 13) + ``WebSocketManager``
(Phase 14) consumers. Two responsibilities:

1. **SSE mirror**: wrap every yielded event in an ``OutboundMessage`` and
   publish to the bus so WebSocket subscribers (and any future channel)
   can fan-out without coupling to ``ChatOrchestrator``.

2. **SSE→WS envelope translation**: WebSocket clients today speak a
   different vocabulary (``delta`` / ``stream_end`` / ``chat_created``
   / ...) than the SSE clients (``message_delta`` / ``done`` / ...).
   The translator preserves both contracts unchanged; downstream
   consumers pick the envelope they expect.

Design goals (per locked plan):

- **Zero SSE contract change** — SSE clients see the exact same wire
  format. Mirror is a side-effect; the SSE generator still yields
  ``{"event": "message", "data": json.dumps(event)}``.
- **WS contract preserved** — existing ``WSServerMsg.*`` constants
  unchanged. Translation is a pure function on the payload dict.
- **Best-effort** — bus publish failures are logged + counters
  incremented, never raised. Adapter must never break the SSE stream.
- **Reusable** — static ``translate_sse_to_ws`` method can be called
  directly by tests or future consumers (e.g. cron → ws push).
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.agent import events as chat_events
from llmwikify.apps.chat.bus.events import (
    OUTBOUND_META_STREAM_DELTA,
    OUTBOUND_META_STREAM_END,
    OutboundMessage,
)
from llmwikify.apps.chat.bus.queue import MessageBus, get_default_bus

logger = logging.getLogger(__name__)


# ─── Translation mapping ──────────────────────────────────────────
#
# Mirrors nanobot v0.2.1 ``channels/bridge.py`` intent: keep the SSE
# vocabulary (the canonical chat event stream) and translate to per-
# channel envelopes on consumption. The mapping is intentionally a
# pure function so it can be tested in isolation and reused by any
# channel consumer.
#
# SSE event types → WS envelope:
#   message_delta        → delta
#   thinking             → thinking
#   done                 → stream_end
#   error                → error
#   tool_call_start      → tool_call (phase=start)
#   tool_call_end        → tool_call (phase=end)
#   tool_call_error      → tool_call (phase=error)
#   confirmation_required → confirmation_required (passthrough)
#   compacted            → compacted (passthrough)
#   phase                → phase (passthrough)
#   save_warning         → save_warning (passthrough)
#   command_done         → command_done (passthrough)
#   research_run_started → research_run_started (passthrough)
#   session_created      → session_created (passthrough)
#   session_init         → session_init (passthrough)
#   timeout              → timeout (passthrough)
#   unknown              → unknown (passthrough + raw field)


class WSTranslatedType:
    """WS envelope type constants (post-translation).

    Kept as a class so we can extend without changing call sites.
    The actual on-wire strings must match ``WSServerMsg.*`` for
    backward compat with existing WS clients.

    Pass4-C (2026-06-22): the 9 passthrough constants are now
    aliases of ``apps.chat.agent.events`` constants, so any rename
    of the canonical SSE type string is reflected here automatically.
    The 5 WS-only translation constants (``DELTA``, ``STREAM_END``,
    ``TOOL_CALL``, ``THINKING``, ``UNKNOWN``) plus ``TIMEOUT`` (a
    WS-only concept, not produced by the SSE side) keep their
    literal string values to match the WS wire protocol.
    """

    # WS-only translated types (post-translation wire strings)
    DELTA = "delta"
    THINKING = "thinking"
    STREAM_END = "stream_end"
    TOOL_CALL = "tool_call"
    UNKNOWN = "unknown"

    # Passthrough: SSE wire name == WS wire name (alias to chat_events)
    ERROR = chat_events.ERROR
    CONFIRMATION_REQUIRED = chat_events.CONFIRMATION_REQUIRED
    COMPACTED = chat_events.COMPACTED
    PHASE = chat_events.PHASE
    SAVE_WARNING = chat_events.SAVE_WARNING
    COMMAND_DONE = chat_events.COMMAND_DONE
    RESEARCH_RUN_STARTED = chat_events.RESEARCH_RUN_STARTED
    SESSION_CREATED = chat_events.SESSION_CREATED
    SESSION_INIT = chat_events.SESSION_INIT

    # WS-only wire string (no SSE source produces this; kept for
    # forward-compat with WS clients that may emit it).
    TIMEOUT = "timeout"


def _delta_envelope(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": WSTranslatedType.DELTA,
        "content": event.get("content", ""),
    }


def _thinking_envelope(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": WSTranslatedType.THINKING,
        "content": event.get("content", ""),
    }


def _stream_end_envelope(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": WSTranslatedType.STREAM_END,
        "content": event.get("content", ""),
    }


def _error_envelope(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": WSTranslatedType.ERROR,
        "error": event.get("message", ""),
    }


def _tool_call_envelope(event: dict[str, Any], phase: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": WSTranslatedType.TOOL_CALL,
        "phase": phase,
        "tool": event.get("tool", ""),
        "call_id": event.get("call_id", ""),
    }
    if phase == "start":
        out["args"] = event.get("args", {})
    elif phase == "end":
        out["result"] = event.get("result")
        # Preserve timing for clients that want to render latency.
        if "duration_ms" in event:
            out["duration_ms"] = event["duration_ms"]
    elif phase == "error":
        out["error"] = event.get("error", "")
        if "duration_ms" in event:
            out["duration_ms"] = event["duration_ms"]
    return out


def _passthrough_envelope(
    event: dict[str, Any], target_type: str,
) -> dict[str, Any]:
    out = dict(event)
    out["type"] = target_type
    return out


# ─── BusAdapter ────────────────────────────────────────────────────


class BusAdapter:
    """Adapter that bridges ``ChatOrchestrator`` SSE yields to MessageBus.

    Public API
    ----------
    - ``mirror_sse_event(event, *, target_id, session_key) -> bool``
      Wrap an SSE event dict as an ``OutboundMessage`` and publish to
      the bus. Returns False on drop (QueueFull).
    - ``translate_sse_to_ws(event) -> dict`` (static)
      Pure SSE→WS envelope translator. No bus interaction.
    - ``set_bus(bus)`` / ``bus()`` — override the default bus.
    - ``stats()`` — bus counters snapshot.

    The adapter does **not** own any sockets or threads; it is a thin
    wrapper around ``MessageBus.publish_outbound`` plus a translation
    helper. Concurrency is inherited from ``MessageBus`` (single-loop
    asyncio, non-blocking publish).
    """

    def __init__(self, bus: MessageBus | None = None) -> None:
        # Default to the process-wide bus; tests can inject their own.
        self._bus: MessageBus | None = bus

    def set_bus(self, bus: MessageBus | None) -> None:
        """Replace the backing bus. ``None`` falls back to ``get_default_bus``."""
        self._bus = bus

    def bus(self) -> MessageBus:
        if self._bus is None:
            return get_default_bus()
        return self._bus

    def mirror_sse_event(
        self,
        event: dict[str, Any],
        *,
        target_id: str = "",
        session_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Publish an SSE event to the bus as an ``OutboundMessage``.

        Args:
            event: the raw dict yielded by ``ChatOrchestrator.chat()``
                (or any producer speaking the SSE vocabulary).
            target_id: per-channel destination. For WS this is the
                ``chat_id``; for HTTP/SSE it's typically empty (fan-out).
            session_key: echoed routing key for consumers.
            metadata: optional namespaced control signals
                (``_meta_*`` keys). If omitted, the adapter auto-tags
                ``message_delta`` / ``thinking`` events with
                ``OUTBOUND_META_STREAM_DELTA`` and ``done`` events
                with ``OUTBOUND_META_STREAM_END``.

        Returns:
            True if the message was enqueued, False if it was dropped
            due to a full outbound queue (logged by the bus).

        Notes:
            Never raises. Bus failures are logged + counted internally.
            The SSE producer path must not be blocked by a slow
            consumer; this is the whole point of the ``publish_outbound``
            non-blocking design.
        """
        if not isinstance(event, dict):
            # Defensive: SSE yield is always a dict, but if a caller
            # passes something else, we wrap it instead of crashing.
            event = {"raw": event}

        # Auto-tag streaming control signals if caller didn't provide.
        meta = dict(metadata) if metadata else {}
        if not meta:
            etype = event.get("type", "")
            if etype in ("message_delta", "thinking"):
                meta[OUTBOUND_META_STREAM_DELTA] = True
            elif etype == "done":
                meta[OUTBOUND_META_STREAM_END] = True

        msg = OutboundMessage(
            channel="http",  # bus adapter defaults to "http" for SSE path
            target_id=target_id,
            session_key=session_key,
            payload=dict(event),
            metadata=meta,
        )
        try:
            return self.bus().publish_outbound(msg)
        except Exception:
            logger.exception("BusAdapter.mirror_sse_event failed")
            return False

    @staticmethod
    def translate_sse_to_ws(event: dict[str, Any]) -> dict[str, Any]:
        """Translate an SSE-shaped event dict to a WS envelope dict.

        Pure function; no side effects, no bus interaction. Safe to
        call from any consumer (WS handler, cron pusher, replay tool).

        The mapping table is intentionally explicit (no ``**event``
        passthrough with type rewrite) so future event types surface
        as ``unknown`` rather than silently changing vocabulary.

        Args:
            event: SSE-style event dict, typically yielded by
                ``ChatOrchestrator.chat()``.

        Returns:
            WS envelope dict, ready to send via
            ``WebSocketManager.send_to_chat``.
        """
        if not isinstance(event, dict):
            return {
                "type": WSTranslatedType.UNKNOWN,
                "raw": event,
            }

        etype = event.get("type", "")

        # ── SSE → WS translation (5 mappings) ──
        if etype == chat_events.MESSAGE_DELTA:
            return _delta_envelope(event)
        if etype == chat_events.THINKING:
            return _thinking_envelope(event)
        if etype == chat_events.DONE:
            return _stream_end_envelope(event)
        if etype == chat_events.ERROR:
            return _error_envelope(event)
        # ── tool_call_start/end/error collapse to one WS envelope ──
        if etype in (
            chat_events.TOOL_CALL_START,
            chat_events.TOOL_CALL_END,
            chat_events.TOOL_CALL_ERROR,
        ):
            # phase = "start" | "end" | "error" (strip the "tool_call_" prefix)
            phase = etype[len("tool_call_"):]
            return _tool_call_envelope(event, phase)
        # ── Passthrough (SSE wire name == WS wire name) ──
        if etype in (
            chat_events.CONFIRMATION_REQUIRED,
            chat_events.COMPACTED,
            chat_events.PHASE,
            chat_events.SAVE_WARNING,
            chat_events.COMMAND_DONE,
            chat_events.RESEARCH_RUN_STARTED,
            chat_events.SESSION_CREATED,
            chat_events.SESSION_INIT,
        ):
            return _passthrough_envelope(event, etype)
        # ── WS-only passthrough (no SSE source; kept for back-compat) ──
        if etype == WSTranslatedType.TIMEOUT:
            return _passthrough_envelope(event, WSTranslatedType.TIMEOUT)
        # Unknown type: preserve verbatim + flag. Consumers should
        # decide whether to render or ignore.
        return {
            "type": WSTranslatedType.UNKNOWN,
            "raw": dict(event),
        }

    def stats(self) -> dict[str, Any]:
        """Snapshot of bus counters (for /api/health or test assertions)."""
        return self.bus().stats()


__all__ = [
    "BusAdapter",
    "WSTranslatedType",
]
