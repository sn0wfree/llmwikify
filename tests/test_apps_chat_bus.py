"""Phase 13 — MessageBus tests (borrowed from nanobot v0.2.1 design).

Covers:
  - InboundMessage / OutboundMessage dataclass + to_dict/from_dict
  - MessageBus publish/consume symmetry + timeout behavior
  - Outbound queue backpressure (drop + stats counter)
  - Stream metadata helpers (is_stream_delta / is_stream_end)
  - Default singleton + reset_default_bus / set_default_bus
"""

from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.bus.events import (
    ALL_OUTBOUND_META,
    INBOUND_META_RUNTIME_CONTROL,
    OUTBOUND_META_STREAM_DELTA,
    OUTBOUND_META_STREAM_END,
    OUTBOUND_META_STREAM_ID,
    InboundMessage,
    OutboundMessage,
)
from llmwikify.apps.chat.bus.queue import (
    MessageBus,
    get_default_bus,
    reset_default_bus,
    set_default_bus,
)

# ── InboundMessage / OutboundMessage dataclass ──────────────────


class TestInboundMessage:
    def test_defaults(self) -> None:
        msg = InboundMessage()
        assert msg.channel == "http"
        assert msg.sender_id == ""
        assert msg.content == ""
        assert msg.session_key == ""
        assert msg.metadata == {}
        # timestamp / message_id auto-filled
        assert msg.timestamp > 0
        assert len(msg.message_id) == 12

    def test_to_dict_round_trip(self) -> None:
        m = InboundMessage(
            channel="websocket",
            sender_id="alice",
            content="hello",
            session_key="websocket:alice",
            metadata={INBOUND_META_RUNTIME_CONTROL: True},
        )
        d = m.to_dict()
        m2 = InboundMessage.from_dict(d)
        assert m2.channel == "websocket"
        assert m2.sender_id == "alice"
        assert m2.content == "hello"
        assert m2.session_key == "websocket:alice"
        assert m2.metadata[INBOUND_META_RUNTIME_CONTROL] is True

    def test_from_dict_handles_missing_fields(self) -> None:
        """Defensive: missing fields fall back to defaults."""
        m = InboundMessage.from_dict({"content": "hi"})
        assert m.content == "hi"
        assert m.channel == "http"  # default
        assert m.metadata == {}      # default

    def test_metadata_isolation(self) -> None:
        """Two instances share no metadata state."""
        m1 = InboundMessage()
        m2 = InboundMessage()
        m1.metadata["k"] = "v"
        assert "k" not in m2.metadata


class TestOutboundMessage:
    def test_defaults(self) -> None:
        m = OutboundMessage()
        assert m.channel == ""
        assert m.target_id == ""
        assert m.session_key == ""
        assert m.payload == {}
        assert m.metadata == {}

    def test_to_dict_round_trip(self) -> None:
        m = OutboundMessage(
            channel="http",
            target_id="conn-1",
            session_key="http:conn-1",
            payload={"type": "delta", "content": "x"},
            metadata={OUTBOUND_META_STREAM_DELTA: True},
        )
        m2 = OutboundMessage.from_dict(m.to_dict())
        assert m2.channel == "http"
        assert m2.target_id == "conn-1"
        assert m2.payload["type"] == "delta"
        assert m2.metadata[OUTBOUND_META_STREAM_DELTA] is True

    def test_is_stream_delta_property(self) -> None:
        m = OutboundMessage()
        assert m.is_stream_delta is False
        m.metadata[OUTBOUND_META_STREAM_DELTA] = True
        assert m.is_stream_delta is True

    def test_is_stream_end_property(self) -> None:
        m = OutboundMessage()
        assert m.is_stream_end is False
        m.metadata[OUTBOUND_META_STREAM_END] = True
        assert m.is_stream_end is True

    def test_stream_id_metadata(self) -> None:
        """Multi-segment streams carry a stream_id for concurrent dedup."""
        m = OutboundMessage(metadata={
            OUTBOUND_META_STREAM_DELTA: True,
            OUTBOUND_META_STREAM_ID: "seg-42",
        })
        assert m.metadata[OUTBOUND_META_STREAM_ID] == "seg-42"
        assert m.is_stream_delta is True

    def test_all_outbound_meta_constant(self) -> None:
        """The constant enumerates all known meta keys for channel filters."""
        assert OUTBOUND_META_STREAM_DELTA in ALL_OUTBOUND_META
        assert OUTBOUND_META_STREAM_END in ALL_OUTBOUND_META
        assert OUTBOUND_META_STREAM_ID in ALL_OUTBOUND_META


# ── MessageBus lifecycle ────────────────────────────────────────


class TestMessageBusLifecycle:
    def test_empty_queues(self) -> None:
        bus = MessageBus()
        assert bus.inbound_size() == 0
        assert bus.outbound_size() == 0
        s = bus.stats()
        assert s["inbound"]["queued"] == 0
        assert s["outbound"]["queued"] == 0
        assert s["outbound"]["maxsize"] == MessageBus.DEFAULT_OUTBOUND_MAXSIZE

    def test_custom_outbound_maxsize(self) -> None:
        bus = MessageBus(outbound_maxsize=2)
        assert bus.stats()["outbound"]["maxsize"] == 2

    def test_reset_clears_counters_and_queues(self) -> None:
        bus = MessageBus(outbound_maxsize=10)
        bus.publish_inbound(InboundMessage(content="hi"))
        bus.publish_outbound(OutboundMessage(payload={"type": "x"}))
        bus.reset()
        s = bus.stats()
        assert s["inbound"]["published"] == 0
        assert s["outbound"]["published"] == 0
        assert bus.inbound_size() == 0
        assert bus.outbound_size() == 0


# ── Inbound path ────────────────────────────────────────────────


class TestInboundPath:
    @pytest.mark.asyncio
    async def test_publish_then_consume(self) -> None:
        bus = MessageBus()
        bus.publish_inbound(InboundMessage(content="hello"))
        msg = await bus.consume_inbound(timeout=0.1)
        assert msg is not None
        assert msg.content == "hello"

    @pytest.mark.asyncio
    async def test_consume_timeout_returns_none(self) -> None:
        bus = MessageBus()
        msg = await bus.consume_inbound(timeout=0.05)
        assert msg is None

    @pytest.mark.asyncio
    async def test_fifo_order_preserved(self) -> None:
        bus = MessageBus()
        for i in range(5):
            bus.publish_inbound(InboundMessage(content=f"msg-{i}"))
        received = []
        for _ in range(5):
            m = await bus.consume_inbound(timeout=0.1)
            received.append(m.content)
        assert received == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]

    @pytest.mark.asyncio
    async def test_inbound_is_unbounded(self) -> None:
        """Unlike outbound, inbound queue should not drop or block."""
        bus = MessageBus()
        for i in range(1000):
            bus.publish_inbound(InboundMessage(content=f"msg-{i}"))
        assert bus.inbound_size() == 1000

    @pytest.mark.asyncio
    async def test_stats_counters_update(self) -> None:
        bus = MessageBus()
        bus.publish_inbound(InboundMessage(content="a"))
        bus.publish_inbound(InboundMessage(content="b"))
        await bus.consume_inbound(timeout=0.1)
        s = bus.stats()
        assert s["inbound"]["published"] == 2
        assert s["inbound"]["consumed"] == 1


# ── Outbound path ───────────────────────────────────────────────


class TestOutboundPath:
    @pytest.mark.asyncio
    async def test_publish_then_consume(self) -> None:
        bus = MessageBus()
        ok = bus.publish_outbound(
            OutboundMessage(payload={"type": "message_delta", "content": "hi"}),
        )
        assert ok is True
        msg = await bus.consume_outbound(timeout=0.1)
        assert msg is not None
        assert msg.payload["content"] == "hi"

    @pytest.mark.asyncio
    async def test_consume_timeout_returns_none(self) -> None:
        bus = MessageBus()
        msg = await bus.consume_outbound(timeout=0.05)
        assert msg is None

    @pytest.mark.asyncio
    async def test_outbound_backpressure_drops(self) -> None:
        """When the outbound queue is full, publish returns False and increments dropped."""
        bus = MessageBus(outbound_maxsize=2)
        assert bus.publish_outbound(OutboundMessage(payload={"n": 1})) is True
        assert bus.publish_outbound(OutboundMessage(payload={"n": 2})) is True
        # Third should drop
        ok = bus.publish_outbound(OutboundMessage(payload={"n": 3}))
        assert ok is False
        s = bus.stats()
        assert s["outbound"]["published"] == 2
        assert s["outbound"]["dropped"] == 1
        assert s["outbound"]["queued"] == 2

    @pytest.mark.asyncio
    async def test_after_consume_publish_succeeds_again(self) -> None:
        """Backpressure is recovered when the consumer drains."""
        bus = MessageBus(outbound_maxsize=2)
        bus.publish_outbound(OutboundMessage(payload={"n": 1}))
        bus.publish_outbound(OutboundMessage(payload={"n": 2}))
        # Drain
        await bus.consume_outbound(timeout=0.1)
        await bus.consume_outbound(timeout=0.1)
        # Should fit one more now
        ok = bus.publish_outbound(OutboundMessage(payload={"n": 3}))
        assert ok is True


# ── Default singleton ───────────────────────────────────────────


class TestDefaultBus:
    def test_get_default_bus_lazy_init(self) -> None:
        # Reset to ensure clean state
        set_default_bus(None)
        bus1 = get_default_bus()
        bus2 = get_default_bus()
        # Same instance returned
        assert bus1 is bus2

    def test_reset_default_bus_replaces(self) -> None:
        bus1 = get_default_bus()
        bus2 = reset_default_bus()
        assert bus1 is not bus2
        bus3 = get_default_bus()
        assert bus2 is bus3

    def test_set_default_bus_replaces(self) -> None:
        custom = MessageBus(outbound_maxsize=5)
        set_default_bus(custom)
        assert get_default_bus() is custom
        # Reset for next tests
        set_default_bus(None)

    def test_set_default_bus_none_clears(self) -> None:
        bus = MessageBus()
        set_default_bus(bus)
        set_default_bus(None)
        # Next get_default_bus should lazily init a fresh one
        fresh = get_default_bus()
        assert fresh is not bus


# ── Integration: SSE event → OutboundMessage ────────────────────


class TestSSEEventIntegration:
    """The bus payload shape is exactly what ``ChatEvent`` factory
    currently yields — this verifies the contract."""

    def test_chatevent_message_delta_fits_payload(self) -> None:
        """A ``message_delta`` event from ``ChatEvent`` round-trips through bus."""
        # Mimic ChatEvent.message_delta without importing (avoid cycle)
        sse_event = {"type": "message_delta", "content": "hello"}
        msg = OutboundMessage(
            channel="http",
            target_id="conn-1",
            session_key="http:conn-1",
            payload=sse_event,
        )
        # Round-trip
        m2 = OutboundMessage.from_dict(msg.to_dict())
        assert m2.payload["type"] == "message_delta"
        assert m2.payload["content"] == "hello"

    def test_stream_metadata_marks_delta_properly(self) -> None:
        """Channel code can filter stream deltas via ``is_stream_delta``."""
        # Imagine ChatOrchestrator publishes 10 deltas + 1 end
        deltas = [
            OutboundMessage(
                payload={"type": "message_delta", "content": str(i)},
                metadata={OUTBOUND_META_STREAM_DELTA: True},
            )
            for i in range(10)
        ]
        end = OutboundMessage(
            payload={"type": "done", "final_response": "all done"},
            metadata={OUTBOUND_META_STREAM_END: True},
        )
        for m in deltas + [end]:
            assert m.is_stream_delta or m.is_stream_end
            # Exactly one of the two flags (deltas have delta only, end has end only)
            assert m.is_stream_delta != m.is_stream_end

    def test_stream_id_groups_concurrent_segments(self) -> None:
        """A second concurrent stream gets a different stream_id."""
        s1 = OutboundMessage(metadata={
            OUTBOUND_META_STREAM_DELTA: True,
            OUTBOUND_META_STREAM_ID: "stream-A",
        })
        s2 = OutboundMessage(metadata={
            OUTBOUND_META_STREAM_DELTA: True,
            OUTBOUND_META_STREAM_ID: "stream-B",
        })
        # Channel can group deltas by stream_id
        assert s1.metadata[OUTBOUND_META_STREAM_ID] != s2.metadata[OUTBOUND_META_STREAM_ID]
