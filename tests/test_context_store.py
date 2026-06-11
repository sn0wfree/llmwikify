"""Tests for ContextStore (LRU + TTL eviction)."""

from __future__ import annotations

import time

from llmwikify.apps.chat.agent.context_store import ContextStore


class TestContextStoreBasic:
    def test_set_get(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", "value_a")
        assert store.get("a") == "value_a"

    def test_get_missing(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        assert store.get("missing") is None

    def test_overwrite(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", "v1")
        store.set("a", "v2")
        assert store.get("a") == "v2"
        assert len(store) == 1

    def test_remove(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", "v1")
        assert store.remove("a") is True
        assert store.get("a") is None
        assert store.remove("a") is False

    def test_contains(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", "v1")
        assert "a" in store
        assert "b" not in store


class TestContextStoreLRU:
    def test_evicts_lru_when_full(self):
        store = ContextStore(max_size=3, ttl_seconds=60)
        store.set("a", 1)
        store.set("b", 2)
        store.set("c", 3)
        # Access "a" to make it recently used
        store.get("a")
        # Adding "d" should evict "b" (LRU)
        store.set("d", 4)
        assert store.get("a") == 1
        assert store.get("b") is None
        assert store.get("c") == 3
        assert store.get("d") == 4

    def test_access_refreshes_lru(self):
        store = ContextStore(max_size=2, ttl_seconds=60)
        store.set("a", 1)
        store.set("b", 2)
        # Touch "a" to make it MRU
        store.get("a")
        # "b" is now LRU, should be evicted
        store.set("c", 3)
        assert store.get("a") == 1
        assert store.get("b") is None

    def test_max_size_respected(self):
        store = ContextStore(max_size=5, ttl_seconds=60)
        for i in range(10):
            store.set(str(i), i)
        assert len(store) == 5
        # Only the last 5 should exist
        for i in range(5):
            assert store.get(str(i)) is None
        for i in range(5, 10):
            assert store.get(str(i)) == i


class TestContextStoreTTL:
    def test_expired_entry_evicted_on_get(self):
        store = ContextStore(max_size=10, ttl_seconds=0.1)
        store.set("a", "v1")
        time.sleep(0.15)
        assert store.get("a") is None

    def test_expired_entry_evicted_on_contains(self):
        store = ContextStore(max_size=10, ttl_seconds=0.1)
        store.set("a", "v1")
        time.sleep(0.15)
        assert "a" not in store

    def test_non_expired_entry_survives(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", "v1")
        assert store.get("a") == "v1"


class TestContextStoreStats:
    def test_stats(self):
        store = ContextStore(max_size=10, ttl_seconds=60)
        store.set("a", 1)
        store.get("a")
        store.get("missing")
        stats = store.stats
        assert stats["size"] == 1
        assert stats["max_size"] == 10
        assert stats["hits"] == 1
