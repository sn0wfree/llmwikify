"""Phase 19-A — BusAdapter unit tests.

Covers:
  - mirror_sse_event: wraps dict into OutboundMessage and publishes
  - mirror_sse_event auto-tags streaming metadata for known types
  - mirror_sse_event auto-tags stream_end for ``done`` events
  - mirror_sse_event does NOT tag non-stream types (e.g. tool_call_start)
  - mirror_sse_event accepts and wraps non-dict payloads defensively
  - mirror_sse_event respects caller-provided metadata (no overwrite)
  - translate_sse_to_ws covers all 13 SSE event types (mapping table)
  - translate_sse_to_ws returns ``unknown`` envelope for unmapped types
  - translate_sse_to_ws handles non-dict input defensively
  - bus singleton default vs injected bus
  - stats() delegates to bus
"""

from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.bus import (
    BusAdapter,
    MessageBus,
    WSTranslatedType,
    get_default_bus,
    reset_default_bus,
)
from llmwikify.apps.chat.bus.adapter import WSTranslatedType as _WT
from llmwikify.apps.chat.bus.events import (
    OUTBOUND_META_STREAM_DELTA,
    OUTBOUND_META_STREAM_END,
    OutboundMessage,
)

# ─── mirror_sse_event: basic wrapping + publish ───────────────────


class TestMirrorSseEventBasics:
    def test_mirror_publishes_outbound_message(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        ok = adapter.mirror_sse_event(
            {"type": "message_delta", "content": "hi"},
            target_id="c1",
            session_key="http:s1",
        )
        assert ok is True
        # Consume the message
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert isinstance(msg, OutboundMessage)
        assert msg.channel == "http"
        assert msg.target_id == "c1"
        assert msg.session_key == "http:s1"
        # Payload preserved verbatim
        assert msg.payload == {"type": "message_delta", "content": "hi"}

    def test_mirror_returns_false_on_drop(self) -> None:
        bus = MessageBus(outbound_maxsize=2)
        adapter = BusAdapter(bus)
        # Fill the queue
        adapter.mirror_sse_event({"type": "x"}, target_id="a")
        adapter.mirror_sse_event({"type": "y"}, target_id="a")
        # Next one should drop
        ok = adapter.mirror_sse_event({"type": "z"}, target_id="a")
        assert ok is False
        assert bus.stats()["outbound"]["dropped"] == 1


# ─── Auto-streaming-metadata tagging ──────────────────────────────


class TestMirrorSseEventAutoMetadata:
    def test_message_delta_auto_tags_stream_delta(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "message_delta", "content": "x"},
            target_id="c",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata.get(OUTBOUND_META_STREAM_DELTA) is True
        assert OUTBOUND_META_STREAM_END not in msg.metadata

    def test_thinking_auto_tags_stream_delta(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "thinking", "content": "x"},
            target_id="c",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata.get(OUTBOUND_META_STREAM_DELTA) is True

    def test_done_auto_tags_stream_end(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "done", "content": "final"},
            target_id="c",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata.get(OUTBOUND_META_STREAM_END) is True
        assert OUTBOUND_META_STREAM_DELTA not in msg.metadata

    def test_tool_call_start_not_tagged(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "tool_call_start", "tool": "x", "args": {}},
            target_id="c",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata == {}

    def test_error_not_tagged(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "error", "message": "boom"},
            target_id="c",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata == {}

    def test_caller_metadata_not_overwritten(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "message_delta", "content": "x"},
            target_id="c",
            metadata={"custom": "tag"},
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.metadata == {"custom": "tag"}


# ─── Defensive input handling ─────────────────────────────────────


class TestMirrorSseEventDefensive:
    def test_non_dict_payload_wrapped(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event("not a dict", target_id="c")  # type: ignore[arg-type]
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        assert msg.payload == {"raw": "not a dict"}

    def test_publish_failure_does_not_raise(self) -> None:
        """A broken bus must not crash the SSE producer path."""

        class BrokenBus(MessageBus):
            def publish_outbound(self, msg: OutboundMessage) -> bool:
                raise RuntimeError("synthetic bus failure")

        adapter = BusAdapter(BrokenBus())
        # Should not raise
        ok = adapter.mirror_sse_event(
            {"type": "x"}, target_id="c",
        )
        assert ok is False


# ─── translate_sse_to_ws: full mapping table coverage ─────────────


class TestTranslateSseToWsDelta:
    def test_message_delta(self) -> None:
        out = BusAdapter.translate_sse_to_ws(
            {"type": "message_delta", "content": "hello"},
        )
        assert out == {"type": _WT.DELTA, "content": "hello"}

    def test_thinking(self) -> None:
        out = BusAdapter.translate_sse_to_ws(
            {"type": "thinking", "content": "step"},
        )
        assert out == {"type": _WT.THINKING, "content": "step"}


class TestTranslateSseToWsStreamEnd:
    def test_done(self) -> None:
        out = BusAdapter.translate_sse_to_ws(
            {"type": "done", "content": "final"},
        )
        assert out == {"type": _WT.STREAM_END, "content": "final"}

    def test_done_missing_content(self) -> None:
        out = BusAdapter.translate_sse_to_ws({"type": "done"})
        assert out["type"] == _WT.STREAM_END
        assert out["content"] == ""


class TestTranslateSseToWsError:
    def test_error(self) -> None:
        out = BusAdapter.translate_sse_to_ws(
            {"type": "error", "message": "boom"},
        )
        assert out == {"type": _WT.ERROR, "error": "boom"}


class TestTranslateSseToWsToolCall:
    def test_tool_call_start(self) -> None:
        out = BusAdapter.translate_sse_to_ws({
            "type": "tool_call_start",
            "tool": "read_file",
            "args": {"path": "/x"},
            "call_id": "c1",
        })
        assert out["type"] == _WT.TOOL_CALL
        assert out["phase"] == "start"
        assert out["tool"] == "read_file"
        assert out["args"] == {"path": "/x"}
        assert out["call_id"] == "c1"

    def test_tool_call_end(self) -> None:
        out = BusAdapter.translate_sse_to_ws({
            "type": "tool_call_end",
            "tool": "read_file",
            "result": "ok",
            "call_id": "c1",
            "duration_ms": 100,
        })
        assert out["type"] == _WT.TOOL_CALL
        assert out["phase"] == "end"
        assert out["result"] == "ok"
        assert out["call_id"] == "c1"
        # duration_ms is preserved (not in canonical envelope but
        # useful for clients that want it; we pass it through)
        assert out["duration_ms"] == 100

    def test_tool_call_error(self) -> None:
        out = BusAdapter.translate_sse_to_ws({
            "type": "tool_call_error",
            "tool": "x",
            "error": "boom",
            "call_id": "c1",
        })
        assert out["type"] == _WT.TOOL_CALL
        assert out["phase"] == "error"
        assert out["error"] == "boom"


class TestTranslateSseToWsPassthrough:
    @pytest.mark.parametrize("sse_type,ws_type", [
        ("confirmation_required", _WT.CONFIRMATION_REQUIRED),
        ("compacted", _WT.COMPACTED),
        ("phase", _WT.PHASE),
        ("save_warning", _WT.SAVE_WARNING),
        ("command_done", _WT.COMMAND_DONE),
        ("research_run_started", _WT.RESEARCH_RUN_STARTED),
        ("session_created", _WT.SESSION_CREATED),
        ("session_init", _WT.SESSION_INIT),
        ("timeout", _WT.TIMEOUT),
    ])
    def test_passthrough_preserves_payload(
        self, sse_type: str, ws_type: str,
    ) -> None:
        ev = {"type": sse_type, "x": 1, "y": "z"}
        out = BusAdapter.translate_sse_to_ws(ev)
        assert out["type"] == ws_type
        # All non-type fields preserved
        assert out["x"] == 1
        assert out["y"] == "z"


class TestTranslateSseToWsUnknown:
    def test_unknown_type_returns_unknown_envelope(self) -> None:
        out = BusAdapter.translate_sse_to_ws(
            {"type": "future_type", "data": "x"},
        )
        assert out["type"] == _WT.UNKNOWN
        assert out["raw"] == {"type": "future_type", "data": "x"}

    def test_non_dict_input_returns_unknown(self) -> None:
        out = BusAdapter.translate_sse_to_ws("not a dict")  # type: ignore[arg-type]
        assert out["type"] == _WT.UNKNOWN
        assert out["raw"] == "not a dict"

    def test_missing_type_returns_unknown(self) -> None:
        out = BusAdapter.translate_sse_to_ws({"content": "x"})
        assert out["type"] == _WT.UNKNOWN


# ─── Singleton + bus injection ────────────────────────────────────


class TestAdapterBusInjection:
    def test_default_bus_when_none_passed(self) -> None:
        # Reset to known state
        reset_default_bus()
        adapter = BusAdapter()
        # Should not raise; uses default bus
        ok = adapter.mirror_sse_event({"type": "x"}, target_id="c")
        assert ok is True

    def test_set_bus_override(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter()
        adapter.set_bus(bus)
        adapter.mirror_sse_event({"type": "x"}, target_id="c")
        # New bus has 1 published
        assert bus.stats()["outbound"]["published"] == 1

    def test_stats_delegates_to_bus(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event({"type": "x"}, target_id="c")
        s = adapter.stats()
        assert s["outbound"]["published"] == 1


# ─── Combined round-trip ──────────────────────────────────────────


class TestRoundTripSseBusWs:
    """End-to-end: SSE event → mirror → consume → translate → WS."""

    def test_full_path_message_delta(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "message_delta", "content": "world"},
            target_id="chat::abc",
            session_key="http:sess1",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        # Translate to WS
        ws_envelope = BusAdapter.translate_sse_to_ws(msg.payload)
        assert ws_envelope == {"type": "delta", "content": "world"}
        # And we can fan-out to WS manager
        from llmwikify.apps.chat.channels.websocket import (
            WebSocketManager,
            _Connection,
        )
        manager = WebSocketManager()
        # Fake conn
        conn = _Connection(
            ws=None,  # type: ignore[arg-type]
            peer="test:0",
            out_queue=asyncio.Queue(),
        )
        manager.attach(conn, "chat::abc")
        n = asyncio.run(manager.send_to_chat("chat::abc", ws_envelope))
        assert n == 1

    def test_full_path_done(self) -> None:
        bus = MessageBus()
        adapter = BusAdapter(bus)
        adapter.mirror_sse_event(
            {"type": "done", "content": "goodbye"},
            target_id="chat::xyz",
        )
        msg = asyncio.run(bus.consume_outbound(timeout=1.0))
        assert msg is not None
        # Stream-end metadata auto-tagged
        assert msg.metadata.get(OUTBOUND_META_STREAM_END) is True
        # Translate to WS
        ws_envelope = BusAdapter.translate_sse_to_ws(msg.payload)
        assert ws_envelope == {"type": "stream_end", "content": "goodbye"}


# ─── WSTranslatedType constants sanity ────────────────────────────


class TestWSTranslatedTypeConstants:
    def test_constants_match_wire_protocol(self) -> None:
        """WS wire strings must match existing WSServerMsg constants."""

        from llmwikify.apps.chat.channels.websocket import WSServerMsg

        assert _WT.DELTA == WSServerMsg.DELTA
        assert _WT.STREAM_END == WSServerMsg.STREAM_END
        assert _WT.ERROR == WSServerMsg.ERROR
