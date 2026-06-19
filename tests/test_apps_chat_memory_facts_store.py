"""Tests for MemoryFactsStore (Phase 6).

Borrowed from nanobot Dream architecture. Tests CRUD:
  - add / get / delete / touch
  - list_by_source / list_all / search
  - count / list_stale
  - idempotent init_schema
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from llmwikify.apps.chat.memory.facts_store import (
    Fact,
    MemoryFactsStore,
)


@pytest.fixture
def store(tmp_path: Path) -> MemoryFactsStore:
    s = MemoryFactsStore(tmp_path / "test.db")
    s.init_schema()
    return s


class TestMemoryFactsStoreInit:
    def test_init_schema_idempotent(self, tmp_path: Path) -> None:
        s = MemoryFactsStore(tmp_path / "test.db")
        s.init_schema()
        s.init_schema()  # no raise

    def test_init_schema_creates_table(self, tmp_path: Path) -> None:
        import sqlite3

        s = MemoryFactsStore(tmp_path / "test.db")
        s.init_schema()
        with sqlite3.connect(s.db_path) as conn:
            cols = conn.execute("PRAGMA table_info(memory_facts)").fetchall()
        col_names = {c[1] for c in cols}
        expected = {
            "id", "content", "source_session_id", "source_type",
            "confidence", "last_referenced_at", "created_at",
        }
        assert expected.issubset(col_names)


class TestMemoryFactsStoreCRUD:
    def test_add_and_get(self, store: MemoryFactsStore) -> None:
        fid = store.add(
            content="Momentum works in A-share",
            source_type="dream_extraction",
            source_session_id="s1",
        )
        fact = store.get(fid)
        assert fact is not None
        assert isinstance(fact, Fact)
        assert fact.id == fid
        assert fact.content == "Momentum works in A-share"
        assert fact.source_type == "dream_extraction"
        assert fact.source_session_id == "s1"
        assert fact.confidence == 1.0
        assert fact.last_referenced_at is None

    def test_add_with_custom_confidence(
        self, store: MemoryFactsStore
    ) -> None:
        fid = store.add(
            content="Maybe mean-reverting",
            source_type="manual",
            confidence=0.7,
        )
        fact = store.get(fid)
        assert fact is not None
        assert fact.confidence == 0.7
        assert fact.source_type == "manual"

    def test_add_with_custom_id(self, store: MemoryFactsStore) -> None:
        fid = store.add(content="x", fact_id="my-id")
        assert fid == "my-id"
        assert store.get("my-id") is not None

    def test_get_not_found(self, store: MemoryFactsStore) -> None:
        assert store.get("nonexistent") is None

    def test_delete(self, store: MemoryFactsStore) -> None:
        fid = store.add(content="x")
        assert store.delete(fid) is True
        assert store.get(fid) is None
        assert store.delete(fid) is False

    def test_touch_updates_last_referenced(
        self, store: MemoryFactsStore
    ) -> None:
        fid = store.add(content="x")
        assert store.touch(fid) is True
        fact = store.get(fid)
        assert fact is not None
        assert fact.last_referenced_at is not None
        assert fact.last_referenced_at > 0

    def test_touch_nonexistent(self, store: MemoryFactsStore) -> None:
        assert store.touch("nonexistent") is False


class TestMemoryFactsStoreQueries:
    def test_list_by_source(self, store: MemoryFactsStore) -> None:
        store.add(content="a", source_type="dream_extraction")
        store.add(content="b", source_type="consolidation")
        store.add(content="c", source_type="dream_extraction")
        store.add(content="d", source_type="manual")

        dreams = store.list_by_source("dream_extraction")
        assert len(dreams) == 2
        cons = store.list_by_source("consolidation")
        assert len(cons) == 1
        assert cons[0].content == "b"

    def test_list_by_source_with_limit(self, store: MemoryFactsStore) -> None:
        for i in range(5):
            store.add(content=f"x{i}", source_type="dream_extraction")
        facts = store.list_by_source("dream_extraction", limit=2)
        assert len(facts) == 2

    def test_list_all(self, store: MemoryFactsStore) -> None:
        store.add(content="a", source_type="dream_extraction")
        store.add(content="b", source_type="manual")
        all_facts = store.list_all()
        assert len(all_facts) == 2

    def test_search_case_insensitive(self, store: MemoryFactsStore) -> None:
        store.add(content="Momentum works", source_type="dream_extraction")
        store.add(content="Mean reversion too", source_type="dream_extraction")
        store.add(content="Volume factor", source_type="dream_extraction")

        results = store.search("momentum")
        assert len(results) == 1
        assert results[0].content == "Momentum works"

        results = store.search("REVERSION")
        assert len(results) == 1
        assert results[0].content == "Mean reversion too"

    def test_search_empty_query(self, store: MemoryFactsStore) -> None:
        store.add(content="x", source_type="dream_extraction")
        assert store.search("") == []

    def test_count(self, store: MemoryFactsStore) -> None:
        assert store.count() == 0
        store.add(content="a", source_type="dream_extraction")
        store.add(content="b", source_type="manual")
        assert store.count() == 2

    def test_list_stale(self, store: MemoryFactsStore) -> None:
        # Add one fact and touch it (fresh)
        fresh = store.add(content="fresh", source_type="dream_extraction")
        store.touch(fresh)

        # Add another fact never touched (stale)
        stale = store.add(content="stale", source_type="dream_extraction")
        # Force staleness by manually setting last_referenced_at to old
        import sqlite3

        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                "UPDATE memory_facts SET last_referenced_at = ? WHERE id = ?",
                (time.time() - 30 * 86400, stale),
            )
            conn.commit()

        stale_facts = store.list_stale(threshold_days=14)
        assert len(stale_facts) == 1
        assert stale_facts[0].id == stale

    def test_to_dict_serialization(self, store: MemoryFactsStore) -> None:
        fid = store.add(
            content="x",
            source_type="consolidation",
            source_session_id="s1",
            confidence=0.5,
        )
        fact = store.get(fid)
        assert fact is not None
        d = fact.to_dict()
        assert d["content"] == "x"
        assert d["source_session_id"] == "s1"
        assert d["confidence"] == 0.5
