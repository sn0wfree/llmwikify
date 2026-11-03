"""A bounded cache for the chat's tool registries.

The orchestrator cached the tool registry of every ``(session, wiki)``
pair it had ever built — and never evicted it. A long-running server
grew one registry per pair for the whole lifetime of the process; the
registries hold tool adapters, wiki handles and (for the parent
registry) a live subagent manager, so the leak was not cheap.

:class:`ToolRegistryCache` is the same mapping the code used before —
``in``, ``[]``, ``[] =``, ``.items()`` — with a size bound and
least-recently-used eviction.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

#: How many registries the cache keeps before evicting the least
#: recently used ones.
DEFAULT_MAX_REGISTRIES = 64


class ToolRegistryCache(MutableMapping):
    """An LRU-bounded mapping of tool registries."""

    def __init__(self, max_entries: int = DEFAULT_MAX_REGISTRIES) -> None:
        # The recency is tracked separately from the data: re-inserting
        # a key on read would mutate the mapping while it is iterated.
        self._data: dict[Any, Any] = {}
        self._order: dict[Any, int] = {}
        self._tick = 0
        self._max_entries = max(1, int(max_entries))

    # ── MutableMapping ────────────────────────────────────────────

    def __getitem__(self, key: Any) -> Any:
        value = self._data[key]
        # Reading makes the entry the most recently used one.
        self._tick += 1
        self._order[key] = self._tick
        return value

    def __setitem__(self, key: Any, value: Any) -> None:
        self._tick += 1
        self._data[key] = value
        self._order[key] = self._tick
        self._evict()

    def __delitem__(self, key: Any) -> None:
        del self._data[key]
        self._order.pop(key, None)

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: Any) -> bool:
        return key in self._data

    # ── internals ─────────────────────────────────────────────────

    def _evict(self) -> None:
        """Drop the least recently used entries above the cap."""
        while len(self._data) > self._max_entries:
            oldest = min(self._order, key=self._order.get)  # type: ignore[arg-type]
            del self._data[oldest]
            del self._order[oldest]

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"ToolRegistryCache({len(self._data)}/{self._max_entries})"


__all__ = ["ToolRegistryCache", "DEFAULT_MAX_REGISTRIES"]
