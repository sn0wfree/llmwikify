"""Tests for MemoryConsolidationStore (Phase 6).

Borrowed from nanobot Consolidator architecture. Tests CRUD:
  - add / get / delete
  - list_by_session (newest first, limit)
  - list_since (cursor-based, used by Dream)
  - latest_for_session
  - count_by_session
  - idempotent init_schema
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from llmwikify.apps.chat.memory.consolidation_store import (
    ConsolidationRecord,
    MemoryConsolidationStore,
)


@pytest.fixture
def store(tmp_path: Path) -> MemoryConsolidationStore:
    s = MemoryConsolidationStore(tmp_path / "test.db")
    s.init_schema()
    return s


class TestMemoryConsolidationStoreInit:
    def test_init_schema_idempotent(self, tmp_path: Path) -> None:
        """Calling init_schema twice should not raise."""
        s = MemoryConsolidationStore(tmp_path / "test.db")
        s.init_schema()
        s.init_schema()  # second call is no-op

    def test_init_schema_creates_table(self, tmp_path: Path) -> None:
        """Schema should include the expected columns."""
        import sqlite3

        s = MemoryConsolidationStore(tmp_path / "test.db")
        s.init_schema()
        with sqlite3.connect(s.db_path) as conn:
            cols = conn.execute(
                "PRAGMA table_info(memory_consolidations)"
            ).fetchall()
        col_names = {c[1] for c in cols}
        expected = {
            "id", "session_id", "start_msg_idx", "end_msg_idx",
            "summary", "md_file_path", "tokens_before",
            "tokens_after", "created_at",
        }
        assert expected.issubset(col_names)


class TestMemoryConsolidationStoreCRUD:
    def test_add_and_get(self, store: MemoryConsolidationStore) -> None:
        cid = store.add(
            session_id="s1",
            start_msg_idx=0,
            end_msg_idx=5,
            summary="User asked about momentum",
        )
        rec = store.get(cid)
        assert rec is not None
        assert isinstance(rec, ConsolidationRecord)
        assert rec.id == cid
        assert rec.session_id == "s1"
        assert rec.start_msg_idx == 0
        assert rec.end_msg_idx == 5
        assert rec.summary == "User asked about momentum"
        assert rec.md_file_path is None
        assert rec.tokens_before is None

    def test_add_with_optional_fields(self, store: MemoryConsolidationStore) -> None:
        cid = store.add(
            session_id="s2",
            start_msg_idx=10,
            end_msg_idx=20,
            summary="Long discussion",
            md_file_path="/home/.llmwikify/memory/sessions/s2.md",
            tokens_before=5000,
            tokens_after=500,
        )
        rec = store.get(cid)
        assert rec is not None
        assert rec.md_file_path == "/home/.llmwikify/memory/sessions/s2.md"
        assert rec.tokens_before == 5000
        assert rec.tokens_after == 500

    def test_add_with_custom_id(self, store: MemoryConsolidationStore) -> None:
        cid = store.add(
            session_id="s3",
            start_msg_idx=0,
            end_msg_idx=1,
            summary="x",
            consolidation_id="custom-id-123",
        )
        assert cid == "custom-id-123"
        assert store.get("custom-id-123") is not None

    def test_get_not_found(self, store: MemoryConsolidationStore) -> None:
        assert store.get("nonexistent-id") is None

    def test_delete(self, store: MemoryConsolidationStore) -> None:
        cid = store.add("s1", 0, 1, "x")
        assert store.delete(cid) is True
        assert store.get(cid) is None
        assert store.delete(cid) is False  # second delete returns False


class TestMemoryConsolidationStoreQueries:
    def test_list_by_session_newest_first(
        self, store: MemoryConsolidationStore
    ) -> None:
        store.add("s1", 0, 5, "first")
        time.sleep(0.01)
        store.add("s1", 5, 10, "second")
        time.sleep(0.01)
        store.add("s1", 10, 15, "third")
        time.sleep(0.01)
        store.add("s2", 0, 5, "other session")

        records = store.list_by_session("s1")
        assert len(records) == 3
        # Newest first: "third" > "second" > "first"
        assert records[0].summary == "third"
        assert records[1].summary == "second"
        assert records[2].summary == "first"

    def test_list_by_session_with_limit(
        self, store: MemoryConsolidationStore
    ) -> None:
        for i in range(5):
            store.add("s1", i, i + 1, f"summary {i}")
        records = store.list_by_session("s1", limit=2)
        assert len(records) == 2

    def test_list_by_session_empty(
        self, store: MemoryConsolidationStore
    ) -> None:
        records = store.list_by_session("nonexistent")
        assert records == []

    def test_list_since_cursor(
        self, store: MemoryConsolidationStore
    ) -> None:
        store.add("s1", 0, 1, "before-cursor")
        time.sleep(0.05)
        cursor = time.time()
        time.sleep(0.05)
        store.add("s1", 1, 2, "after-cursor")

        records = store.list_since(cursor)
        assert len(records) == 1
        assert records[0].summary == "after-cursor"

    def test_list_since_with_limit(
        self, store: MemoryConsolidationStore
    ) -> None:
        for i in range(10):
            store.add("s1", i, i + 1, f"x{i}")
            time.sleep(0.005)
        records = store.list_since(0, limit=3)
        assert len(records) == 3

    def test_latest_for_session(
        self, store: MemoryConsolidationStore
    ) -> None:
        store.add("s1", 0, 1, "old")
        time.sleep(0.01)
        store.add("s1", 1, 2, "new")
        latest = store.latest_for_session("s1")
        assert latest is not None
        assert latest.summary == "new"

    def test_latest_for_session_empty(
        self, store: MemoryConsolidationStore
    ) -> None:
        assert store.latest_for_session("nonexistent") is None

    def test_count_by_session(
        self, store: MemoryConsolidationStore
    ) -> None:
        store.add("s1", 0, 1, "a")
        store.add("s1", 1, 2, "b")
        store.add("s2", 0, 1, "c")
        assert store.count_by_session("s1") == 2
        assert store.count_by_session("s2") == 1
        assert store.count_by_session("nope") == 0

    def test_to_dict_serialization(
        self, store: MemoryConsolidationStore
    ) -> None:
        cid = store.add("s1", 0, 1, "x")
        rec = store.get(cid)
        assert rec is not None
        d = rec.to_dict()
        assert d["session_id"] == "s1"
        assert d["start_msg_idx"] == 0
        assert d["summary"] == "x"
