"""Phase 13/19-A — In-process pub/sub for chat/agent messages.

Public surface
--------------
- ``InboundMessage`` / ``OutboundMessage``: bus event dataclasses
  (Phase 13).
- ``MessageBus``: dual-queue async pub/sub (Phase 13).
- ``BusAdapter``: SSE→bus mirror + SSE→WS envelope translator
  (Phase 19-A).
- Singleton helpers: ``get_default_bus`` / ``set_default_bus`` /
  ``reset_default_bus`` / ``get_default_ws_manager`` (re-exported
  from ``channels.websocket``).
"""

from llmwikify.apps.chat.bus.adapter import BusAdapter, WSTranslatedType
from llmwikify.apps.chat.bus.events import (
    ALL_OUTBOUND_META,
    INBOUND_META_RESUMED,
    INBOUND_META_RUNTIME_CONTROL,
    OUTBOUND_META_PROGRESS,
    OUTBOUND_META_RETRY_WAIT,
    OUTBOUND_META_STREAM_DELTA,
    OUTBOUND_META_STREAM_END,
    OUTBOUND_META_STREAM_ID,
    OUTBOUND_META_WANTS_STREAM,
    InboundMessage,
    OutboundMessage,
)
from llmwikify.apps.chat.bus.queue import (
    MessageBus,
    get_default_bus,
    reset_default_bus,
    set_default_bus,
)

__all__ = [
    "BusAdapter",
    "WSTranslatedType",
    "InboundMessage",
    "OutboundMessage",
    "MessageBus",
    "get_default_bus",
    "reset_default_bus",
    "set_default_bus",
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
