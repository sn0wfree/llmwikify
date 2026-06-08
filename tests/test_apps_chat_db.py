"""Unit tests for the v0.32 Phase 3 ChatDatabase changes.

Focuses on the **new** features (research_steps table, save/
load_research_state) and the consolidated behavior
(AutoResearchDatabase is now an alias for ChatDatabase,
get_autoresearch_db_path is now an alias for get_chat_db_path).

The full table CRUD (sessions/sub_queries/sources) is
covered by tests/test_autoresearch.py which is the
backward-compat test suite for the consolidated class.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from llmwikify.apps.chat.db import (
    AutoResearchDatabase,
    ChatDatabase,
    DB_SIZE_WARNING_MB,
    get_autoresearch_db_path,
    get_chat_db_path,
)


@pytest.fixture
def fresh_db() -> ChatDatabase:
    """A fresh ChatDatabase in a temp dir per test."""
    with tempfile.TemporaryDirectory() as tmp:
        yield ChatDatabase(tmp)


@pytest.fixture
def db_with_session() -> tuple[ChatDatabase, str]:
    """A ChatDatabase with one pre-created session."""
    with tempfile.TemporaryDirectory() as tmp:
        db = ChatDatabase(tmp)
        sid = db.create_research_session("wiki-1", "what is X?")
        yield db, sid


# ─── Identity & path-helper aliases ──────────────────────────────


class TestIdentityAndPaths:
    def test_autoresearch_is_alias_for_chat(self) -> None:
        assert AutoResearchDatabase is ChatDatabase

    def test_path_helpers_return_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assert get_chat_db_path(tmp) == get_autoresearch_db_path(tmp)
            # Both return the canonical .llmwiki_agent.db filename
            # (auto-migrated from autoresearch.db in v0.33.0)
            assert get_chat_db_path(tmp).name == ".llmwiki_agent.db"

    def test_canonical_path_under_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = get_chat_db_path(tmp)
            assert p.parent == Path(tmp)
            assert p.name == ".llmwiki_agent.db"

    def test_size_warning_threshold_exported(self) -> None:
        assert DB_SIZE_WARNING_MB == 100


# ─── Schema creation (CREATE TABLE IF NOT EXISTS) ──────────────


class TestSchema:
    def test_all_four_tables_created(self, fresh_db: ChatDatabase) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            import sqlite3
            with sqlite3.connect(db.db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            # 3 pre-Phase-3 research tables
            assert "autoresearch_sessions" in tables
            assert "autoresearch_sub_queries" in tables
            assert "autoresearch_sources" in tables
            # NEW Phase 3 table
            assert "research_steps" in tables

    def test_research_steps_columns(self, fresh_db: ChatDatabase) -> None:
        import sqlite3
        with sqlite3.connect(fresh_db.db_path) as conn:
            cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(research_steps)"
                ).fetchall()
            }
        expected = {
            "id", "session_id", "step_num", "action", "thought",
            "status", "result_json", "duration_ms", "created_at",
        }
        assert expected.issubset(cols)

    def test_research_steps_indexes(self, fresh_db: ChatDatabase) -> None:
        import sqlite3
        with sqlite3.connect(fresh_db.db_path) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        # Pre-Phase-3 indexes
        assert "idx_ar_sub_queries_session" in indexes
        assert "idx_ar_sources_session" in indexes
        # NEW Phase 3 index
        assert "idx_research_steps_session" in indexes

    def test_idempotent_re_instantiation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db1 = ChatDatabase(tmp)
            db2 = ChatDatabase(tmp)  # should not raise
            assert db1.db_path == db2.db_path


# ─── research_steps CRUD (NEW in Phase 3) ──────────────────────


class TestResearchSteps:
    def test_save_step_minimal(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        step_id = db.save_step(sid, 0, action="plan")
        assert isinstance(step_id, str)
        assert len(step_id) > 0

    def test_save_step_full(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(
            sid, 0, action="plan", status="done",
            thought="plan the query", result={"plan": "step 1: search"},
            duration_ms=150,
        )
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["action"] == "plan"
        assert step["status"] == "done"
        assert step["thought"] == "plan the query"
        assert step["duration_ms"] == 150
        assert step["result"] == {"plan": "step 1: search"}

    def test_get_step_missing_returns_none(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        assert db.get_step(sid, 999) is None

    def test_list_steps_ordered_by_step_num(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 2, action="synthesize")
        db.save_step(sid, 0, action="plan")
        db.save_step(sid, 1, action="gather")
        steps = db.list_steps(sid)
        assert [s["step_num"] for s in steps] == [0, 1, 2]
        assert [s["action"] for s in steps] == ["plan", "gather", "synthesize"]

    def test_list_steps_empty_for_unknown_session(self, fresh_db: ChatDatabase) -> None:
        assert fresh_db.list_steps("nonexistent-id") == []

    def test_save_step_replaces_on_unique_conflict(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        """The UNIQUE(session_id, step_num) constraint means
        save_step with INSERT OR REPLACE updates the existing row."""
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan", status="pending",
                    result={"v": 1})
        db.save_step(sid, 0, action="plan", status="done",
                    result={"v": 2})
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["status"] == "done"
        assert step["result"] == {"v": 2}
        # Only one row, not two
        assert len(db.list_steps(sid)) == 1

    def test_update_step_status(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan", status="pending")
        db.update_step_status(sid, 0, "done")
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["status"] == "done"

    def test_delete_steps_cascades(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan")
        db.save_step(sid, 1, action="gather")
        deleted = db.delete_steps(sid)
        assert deleted == 2
        assert db.list_steps(sid) == []

    def test_delete_steps_unknown_session(self, fresh_db: ChatDatabase) -> None:
        assert fresh_db.delete_steps("nope") == 0


# ─── save_research_state / load_research_state ───────────────────


class TestResearchStatePersistence:
    """Phase 3 NEW: the 15+ ResearchState fields are now
    persisted via save_research_state()."""

    def test_save_load_round_trip(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        state = {
            "round": 1,
            "max_rounds": 5,
            "max_replan": 2,
            "phase": "gather",
            "sub_queries": [{"q": "a"}, {"q": "b"}],
            "sources": [{"url": "x"}],
            "synthesis": None,
            "report_md": None,
            "review": None,
            "knowledge_gaps": ["gap 1"],
            "contradictions": [],
            "issues": ["issue 1", "issue 2"],
            "observations": ["obs"],
            "_last_thought": "thinking...",
            "cancelled": False,
            "paused": False,
            "budget_remaining": 0.85,
        }
        db.save_research_state(sid, 1, state)
        loaded = db.load_research_state(sid, 1)
        assert loaded == state

    def test_save_research_state_uses_phase_as_action(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        state = {"round": 0, "phase": "plan", "sub_queries": []}
        db.save_research_state(sid, 0, state)
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["action"] == "plan"
        assert step["status"] == "done"

    def test_save_research_state_default_action_when_no_phase(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        state = {"round": 0}  # no "phase" key
        db.save_research_state(sid, 0, state)
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["action"] == "unknown"

    def test_load_research_state_missing_step(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        assert db.load_research_state(sid, 99) is None


# ─── Cascade delete covers steps ─────────────────────────────────


class TestCascadeDelete:
    def test_delete_research_removes_steps(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan")
        db.save_step(sid, 1, action="gather")
        assert db.delete_research(sid) is True
        assert db.list_steps(sid) == []


# ─── Step result_json encoding edge cases ────────────────────────


class TestResultJsonEdgeCases:
    def test_empty_result_means_none(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan", result=None)
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["result"] is None

    def test_unicode_in_result(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        db.save_step(sid, 0, action="plan",
                    result={"observation": "中文 emoji 🎉"})
        step = db.get_step(sid, 0)
        assert step is not None
        assert step["result"]["observation"] == "中文 emoji 🎉"

    def test_nested_result(
        self, db_with_session: tuple[ChatDatabase, str]
    ) -> None:
        db, sid = db_with_session
        state = {
            "level1": {
                "level2": {
                    "level3": [1, 2, 3],
                    "level3_str": "deep",
                }
            }
        }
        db.save_research_state(sid, 0, state)
        loaded = db.load_research_state(sid, 0)
        assert loaded == state
