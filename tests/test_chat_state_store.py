"""Tests for the session state store and the bounded registry cache.

The orchestrator used to keep two unbounded dictionaries in the process:
the session status (one entry per session, never evicted) and the tool
registry cache (one entry per (session, wiki) pair, never evicted).
Both are now bounded, and the status can be externalised so that a
second instance sees that a session is busy.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from llmwikify.apps.chat.agent.registry_cache import ToolRegistryCache
from llmwikify.apps.chat.agent.state_store import (
    DictSessionStateStore,
    InMemorySessionStateStore,
    SessionState,
    SessionStateStore,
    SessionStateView,
    SqliteSessionStateStore,
)

# ── InMemorySessionStateStore ───────────────────────────────────────


def test_the_store_starts_empty() -> None:
    store = InMemorySessionStateStore()
    assert store.get("s1").status == "idle"
    assert store.list_all() == {}


def test_set_and_get() -> None:
    store = InMemorySessionStateStore()
    store.set("s1", "busy")
    assert store.get("s1").status == "busy"
    assert store.list_all()["s1"].status == "busy"


def test_clear_forgets_the_session() -> None:
    store = InMemorySessionStateStore()
    store.set("s1", "busy")
    store.clear("s1")
    assert store.get("s1").status == "idle"
    assert store.list_all() == {}


def test_the_entry_cap_evicts_the_least_recently_used() -> None:
    """The dict used to grow without bound — now it has a cap."""
    store = InMemorySessionStateStore(max_sessions=3)
    for i in range(5):
        store.set(f"s{i}", "busy")
    assert len(store) == 3
    # the two oldest are gone, the three newest are still there
    assert store.get("s0").status == "idle"
    assert store.get("s4").status == "busy"


def test_reading_an_entry_makes_it_recent() -> None:
    """A session that is looked at is not the next to be evicted."""
    store = InMemorySessionStateStore(max_sessions=2)
    store.set("a", "busy")
    store.set("b", "busy")
    store.get("a")  # 'a' becomes the most recently used
    store.set("c", "busy")
    assert store.get("a").status == "busy"
    assert store.get("b").status == "idle"


def test_the_ttl_drops_stale_entries() -> None:
    """An entry that was not touched for the TTL is gone."""
    store = InMemorySessionStateStore(ttl_seconds=0.01)
    store.set("s1", "busy")
    time.sleep(0.02)
    assert store.get("s1").status == "idle"
    assert store.list_all() == {}


def test_an_expired_lease_reads_as_idle() -> None:
    """A lease that ran out is no lease."""
    store = InMemorySessionStateStore()
    store.set("s1", "busy", holder="inst-1", ttl=0.01)
    time.sleep(0.02)
    assert store.get("s1").status == "idle"
    assert store.get("s1").busy is False


def test_a_live_lease_is_busy() -> None:
    store = InMemorySessionStateStore()
    store.set("s1", "busy", holder="inst-1", ttl=60)
    state = store.get("s1")
    assert state.busy is True
    assert state.holder == "inst-1"


# ── DictSessionStateStore (the legacy path) ─────────────────────────


def test_the_dict_store_keeps_the_dict_as_the_source_of_truth() -> None:
    """A plain dict still works — it stays the caller's dict."""
    data: dict[str, str] = {}
    store = DictSessionStateStore(data)
    store.set("s1", "busy")
    assert data == {"s1": "busy"}
    assert store.get("s1").status == "busy"
    data["s2"] = "idle"
    assert store.get("s2").status == "idle"
    store.clear("s1")
    assert "s1" not in data


# ── SessionStateView ────────────────────────────────────────────────


def test_the_view_is_dict_like() -> None:
    """The legacy surface: ``view["s1"] = "busy"`` and ``view["s1"]``."""
    store = InMemorySessionStateStore()
    view = SessionStateView(store)
    view["s1"] = "busy"
    assert view["s1"] == "busy"
    assert store.get("s1").status == "busy"
    assert "s1" in view
    assert len(view) == 1
    del view["s1"]
    assert store.get("s1").status == "idle"


def test_the_view_reads_through_to_the_dict() -> None:
    """Mutating the caller's dict is visible through the view."""
    data: dict[str, str] = {}
    store = DictSessionStateStore(data)
    view = SessionStateView(store)
    data["s1"] = "busy"
    assert view["s1"] == "busy"


def test_the_view_raises_for_an_unknown_key() -> None:
    store = InMemorySessionStateStore()
    view = SessionStateView(store)
    with pytest.raises(KeyError):
        view["nope"]


# ── SqliteSessionStateStore ─────────────────────────────────────────


class _FakeDB:
    """A minimal stand-in for the chat DB facade."""

    def __init__(self) -> None:
        self.metadata: dict[str, dict[str, Any]] = {}

    def get_session_metadata(self, session_id: str) -> dict[str, Any]:
        return dict(self.metadata.get(session_id, {}))

    def set_session_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        self.metadata[session_id] = dict(metadata)

    def update_session_metadata(self, session_id: str, **patch: Any) -> dict[str, Any]:
        current = self.metadata.setdefault(session_id, {})
        current.update(patch)
        return dict(current)

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        return [{"id": sid} for sid in self.metadata]


def test_the_sqlite_store_persists_the_state() -> None:
    db = _FakeDB()
    store = SqliteSessionStateStore(db, instance_id="inst-1")
    store.set("s1", "busy", holder="inst-1")
    assert db.metadata["s1"]["session_state"]["status"] == "busy"


def test_the_sqlite_store_survives_a_new_instance() -> None:
    """A second instance sees what the first one wrote."""
    db = _FakeDB()
    first = SqliteSessionStateStore(db, instance_id="inst-1")
    first.set("s1", "busy", holder="inst-1")
    second = SqliteSessionStateStore(db, instance_id="inst-2")
    assert second.get("s1").status == "busy"
    assert second.get("s1").holder == "inst-1"


def test_the_lease_blocks_another_instance() -> None:
    """Two instances must not drive the same session at once."""
    db = _FakeDB()
    first = SqliteSessionStateStore(db, instance_id="inst-1")
    second = SqliteSessionStateStore(db, instance_id="inst-2")

    assert first.try_acquire("s1") is True
    assert second.try_acquire("s1") is False
    # the holder may re-acquire
    assert first.try_acquire("s1") is True


def test_an_expired_lease_can_be_taken_over() -> None:
    """A crashed instance must not lock the session forever."""
    db = _FakeDB()
    first = SqliteSessionStateStore(db, instance_id="inst-1")
    second = SqliteSessionStateStore(db, instance_id="inst-2")
    assert first.try_acquire("s1", ttl=0.01) is True
    time.sleep(0.02)
    assert second.try_acquire("s1") is True


def test_release_gives_the_lease_back() -> None:
    db = _FakeDB()
    store = SqliteSessionStateStore(db, instance_id="inst-1")
    assert store.try_acquire("s1") is True
    store.release("s1")
    assert store.get("s1").status == "idle"


def test_clear_removes_the_state_from_the_metadata() -> None:
    db = _FakeDB()
    store = SqliteSessionStateStore(db, instance_id="inst-1")
    db.metadata["s1"] = {"goal_state": {"x": 1}}
    store.set("s1", "busy", holder="inst-1")
    store.clear("s1")
    assert "session_state" not in db.metadata["s1"]
    # the other metadata is untouched
    assert db.metadata["s1"]["goal_state"] == {"x": 1}


def test_the_sqlite_store_survives_a_broken_db() -> None:
    """A DB error must not take the chat down."""

    class Broken:
        def get_session_metadata(self, session_id):
            raise RuntimeError("db is gone")

        def set_session_metadata(self, session_id, metadata):
            raise RuntimeError("db is gone")

        def update_session_metadata(self, session_id, **patch):
            raise RuntimeError("db is gone")

        def list_chat_sessions(self):
            raise RuntimeError("db is gone")

    store = SqliteSessionStateStore(Broken(), instance_id="inst-1")
    store.set("s1", "busy")
    assert store.get("s1").status == "idle"


# ── ToolRegistryCache ──────────────────────────────────────────────


def test_the_registry_cache_is_a_mapping() -> None:
    cache = ToolRegistryCache()
    cache[("s1", "w1")] = "registry"
    assert ("s1", "w1") in cache
    assert cache[("s1", "w1")] == "registry"
    assert dict(cache.items()) == {("s1", "w1"): "registry"}
    del cache[("s1", "w1")]
    assert len(cache) == 0


def test_the_registry_cache_evicts_the_least_recently_used() -> None:
    """The leak: one registry per (session, wiki) pair, forever."""
    cache = ToolRegistryCache(max_entries=2)
    cache[("s1", "w1")] = "a"
    cache[("s2", "w2")] = "b"
    cache[("s3", "w3")] = "c"
    assert len(cache) == 2
    assert ("s1", "w1") not in cache
    assert ("s3", "w3") in cache


def test_the_registry_cache_keeps_the_used_entry() -> None:
    cache = ToolRegistryCache(max_entries=2)
    cache[("s1", "w1")] = "a"
    cache[("s2", "w2")] = "b"
    cache[("s1", "w1")]  # 'a' becomes the most recently used
    cache[("s3", "w3")] = "c"
    assert ("s1", "w1") in cache
    assert ("s2", "w2") not in cache


def test_the_registry_cache_never_exceeds_its_cap() -> None:
    cache = ToolRegistryCache(max_entries=8)
    for i in range(100):
        cache[(f"s{i}", "w1")] = i
    assert len(cache) == 8


# ── the store contract ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "store_factory",
    [
        lambda: InMemorySessionStateStore(),
        lambda: DictSessionStateStore({}),
    ],
)
def test_both_stores_satisfy_the_contract(store_factory) -> None:
    store = store_factory()
    assert isinstance(store, SessionStateStore)
    store.set("s1", "busy")
    assert store.get("s1").status == "busy"
    assert "s1" in store.list_all()
    store.clear("s1")
    assert store.get("s1").status == "idle"


def test_session_state_defaults() -> None:
    state = SessionState()
    assert state.status == "idle"
    assert state.holder == ""
    assert state.expires_at == 0.0
    assert state.expired is False
    assert state.busy is False


# ── the orchestrator wiring ─────────────────────────────────────────


def test_the_orchestrator_uses_the_bounded_cache_and_the_store() -> None:
    """The two leaking dicts are gone from the orchestrator."""
    import inspect

    from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

    src = inspect.getsource(ChatOrchestrator.__init__)
    assert "ToolRegistryCache()" in src
    assert "InMemorySessionStateStore()" in src
    assert "self._tool_registries: dict[" not in src


def test_the_orchestrator_accepts_an_injected_store() -> None:
    """A multi-instance deployment injects the SQLite store."""
    import inspect

    from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

    sig = inspect.signature(ChatOrchestrator.__init__)
    assert "state_store" in sig.parameters


def test_the_session_manager_accepts_a_store() -> None:
    """The manager reads through the store, not a raw dict."""
    import inspect

    from llmwikify.apps.chat.agent.session_manager import SessionManager

    sig = inspect.signature(SessionManager.__init__)
    assert "state_store" in sig.parameters
    src = inspect.getsource(SessionManager.get_session_status)
    assert "_state_store.get(" in src
