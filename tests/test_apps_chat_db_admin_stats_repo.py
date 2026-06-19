"""Tests for AdminStatsRepository (cross-table admin/stats).

These tests use ChatDatabase to seed data because AdminStats reads
across multiple tables (chat_sessions, dream_proposals, etc.).
Direct inserts via the individual repos would also work.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import (
    AdminStatsRepository,
    AutoResearchDatabase,
)


@pytest.fixture
def admin(tmp_path: Path) -> AdminStatsRepository:
    """AdminStatsRepository backed by a fresh AutoResearchDatabase.

    AutoResearchDatabase (not ChatDatabase) is used because
    admin/stats queries span tables owned by all 3 facades
    (chat, research, wiki). AutoResearchDatabase inits all
    of them so queries don't fail with ``no such table``.
    """
    db = AutoResearchDatabase(tmp_path)
    return db._admin


@pytest.fixture
def seeded_db(tmp_path: Path) -> AutoResearchDatabase:
    """AutoResearchDatabase seeded with chat data."""
    db = AutoResearchDatabase(tmp_path)
    sid = db.create_chat_session(wiki_id="wiki-A")
    db.save_chat_message({
        "session_id": sid, "role": "user", "content": "hi",
    })
    db.log_tool_call(sid, "echo", {"x": 1})
    return db


# ─── get_wiki_stats ─────────────────────────────────────────────


class TestGetWikiStats:
    def test_empty_wiki_returns_zero_counts(
        self, admin: AdminStatsRepository,
    ) -> None:
        stats = admin.get_wiki_stats("nonexistent-wiki")
        assert stats["wiki_id"] == "nonexistent-wiki"
        # All counts should be 0
        for _table, count in stats["counts"].items():
            assert count == 0, f"{_table} should be 0"

    def test_counts_chat_sessions(
        self, seeded_db: AutoResearchDatabase,
    ) -> None:
        stats = seeded_db.get_wiki_stats("wiki-A")
        assert stats["counts"]["chat_sessions"] == 1
        assert stats["counts"]["research_sessions"] == 0


# ─── list_all_wikis ─────────────────────────────────────────────


class TestListAllWikis:
    def test_empty_returns_empty_list(
        self, admin: AdminStatsRepository,
    ) -> None:
        assert admin.list_all_wikis() == []

    def test_returns_seeded_wiki(
        self, seeded_db: AutoResearchDatabase,
    ) -> None:
        wikis = seeded_db.list_all_wikis()
        assert {"wiki_id": "wiki-A"} in wikis


# ─── delete_wiki_data ───────────────────────────────────────────


class TestDeleteWikiData:
    def test_returns_zero_for_unknown_wiki(
        self, admin: AdminStatsRepository,
    ) -> None:
        result = admin.delete_wiki_data("nonexistent")
        assert result["wiki_id"] == "nonexistent"
        for _table, count in result["deleted"].items():
            assert count == 0

    def test_deletes_chat_sessions_for_wiki(
        self, seeded_db: AutoResearchDatabase,
    ) -> None:
        # Capture the session id before deletion
        sessions_before = seeded_db.list_chat_sessions()
        assert len(sessions_before) == 1
        sid = sessions_before[0]["id"]
        # Delete
        result = seeded_db.delete_wiki_data("wiki-A")
        assert result["deleted"]["chat_sessions"] == 1
        # Verify the session is gone
        assert seeded_db.get_chat_session(sid) is None


# ─── export_wiki_data ───────────────────────────────────────────


class TestExportWikiData:
    def test_empty_export(self, admin: AdminStatsRepository) -> None:
        data = admin.export_wiki_data("nonexistent")
        assert data["wiki_id"] == "nonexistent"
        # Tables are present but empty
        assert data["chat_sessions"] == []
        assert data["dream_proposals"] == []
        assert data["notifications"] == []

    def test_export_includes_seeded_sessions(
        self, seeded_db: AutoResearchDatabase,
    ) -> None:
        data = seeded_db.export_wiki_data("wiki-A")
        assert len(data["chat_sessions"]) == 1
        assert data["chat_sessions"][0]["wiki_id"] == "wiki-A"


# ─── get_db_stats ───────────────────────────────────────────────


class TestGetDbStats:
    def test_returns_table_counts_and_size(
        self, seeded_db: AutoResearchDatabase,
    ) -> None:
        stats = seeded_db.get_db_stats()
        assert "tables" in stats
        assert "size_mb" in stats
        # chat_sessions has 1 entry
        assert stats["tables"]["chat_sessions"] == 1
        assert stats["tables"]["chat_messages"] == 1
        assert stats["tables"]["tool_calls"] == 1
        # Unknown tables are 0
        assert stats["tables"]["dream_proposals"] == 0

    def test_size_mb_is_positive(self, seeded_db: AutoResearchDatabase) -> None:
        stats = seeded_db.get_db_stats()
        assert stats["size_mb"] >= 0

    def test_empty_db_returns_all_zeros(
        self, admin: AdminStatsRepository,
    ) -> None:
        stats = admin.get_db_stats()
        for table, count in stats["tables"].items():
            assert count == 0, f"{table} should be 0"
