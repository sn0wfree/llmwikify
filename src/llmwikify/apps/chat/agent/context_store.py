"""LRU + TTL context store for AgentContext objects.

Prevents unbounded memory growth from in-memory conversation
contexts by evicting least-recently-used entries after a
configurable TTL and enforcing a maximum capacity.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)


class ContextStore:
    """Bounded LRU dict with per-entry TTL eviction.

    Items are evicted when:
      - Capacity is exceeded (LRU eviction)
      - Their TTL has expired (checked on get/set/eviction sweep)
    """

    def __init__(self, max_size: int = 200, ttl_seconds: float = 1800):
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._evictions = 0

    def get(self, key: str) -> Any | None:
        """Get an entry, refreshing its LRU position and checking TTL."""
        entry = self._data.get(key)
        if entry is None:
            return None
        value, ts = entry
        if self._is_expired(ts):
            del self._data[key]
            self._evictions += 1
            logger.debug("ContextStore: evicted expired entry %s", key)
            return None
        # Move to end (most recently used)
        self._data.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        """Set an entry, evicting LRU if over capacity."""
        now = time.monotonic()
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = (value, now)
            return
        # Evict LRU entries that are expired first
        self._sweep_expired()
        # If still over capacity, evict LRU
        while len(self._data) >= self._max_size:
            evicted_key, _ = self._data.popitem(last=False)
            self._evictions += 1
            logger.debug("ContextStore: LRU evicted %s", evicted_key)
        self._data[key] = (value, now)

    def remove(self, key: str) -> bool:
        """Remove an entry. Returns True if it existed."""
        if key in self._data:
            del self._data[key]
            return True
        return False

    def __contains__(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        _, ts = entry
        if self._is_expired(ts):
            del self._data[key]
            self._evictions += 1
            return False
        return True

    def __len__(self) -> int:
        return len(self._data)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "size": len(self._data),
            "max_size": self._max_size,
            "hits": self._hits,
            "evictions": self._evictions,
        }

    def _is_expired(self, ts: float) -> bool:
        return (time.monotonic() - ts) > self._ttl_seconds

    def _sweep_expired(self) -> None:
        """Remove all expired entries (full sweep)."""
        now = time.monotonic()
        expired = [
            k for k, (_, ts) in self._data.items()
            if (now - ts) > self._ttl_seconds
        ]
        for k in expired:
            del self._data[k]
            self._evictions += 1
        if expired:
            logger.debug("ContextStore: swept %d expired entries", len(expired))
