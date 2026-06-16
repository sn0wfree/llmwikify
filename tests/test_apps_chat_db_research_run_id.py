"""Unit tests for v0.41 research_run_id column on chat_messages.

Covers:
  - DB migration adds the column on legacy DBs (idempotent).
  - save_chat_message persists research_run_id and get_chat_messages reads it.
  - None / missing research_run_id → NULL column, no crash.
  - The new column is included in the SELECT * return shape (frontend relies).
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ChatDatabase


@pytest.fixture
def db() -> ChatDatabase:
    """A fresh ChatDatabase in a temp dir per test."""
    with tempfile.TemporaryDirectory() as tmp:
        yield ChatDatabase(tmp)


def test_research_run_id_column_exists_on_fresh_db(db: ChatDatabase) -> None:
    """Fresh DB: column created during _init_db."""
    with sqlite3.connect(db.db_path) as conn:
        rows = conn.execute("PRAGMA table_info(chat_messages)").fetchall()
    cols = {r[1] for r in rows}
    assert "research_run_id" in cols, (
        f"research_run_id missing from fresh schema; got: {sorted(cols)}"
    )


def test_research_run_id_column_added_to_legacy_db(tmp_path: Path) -> None:
    """Legacy DB (no research_run_id) gets the column via migration."""
    db = ChatDatabase(tmp_path)
    # Simulate a v0.40 DB by dropping the column after init
    with sqlite3.connect(db.db_path) as conn:
        # Recreate table without the column (SQLite supports DROP COLUMN since 3.35)
        try:
            conn.execute("ALTER TABLE chat_messages DROP COLUMN research_run_id")
        except sqlite3.OperationalError:
            pytest.skip("SQLite too old to drop column")
        conn.commit()
    # Re-init: should add the column back
    db._init_db()
    with sqlite3.connect(db.db_path) as conn:
        rows = conn.execute("PRAGMA table_info(chat_messages)").fetchall()
    cols = {r[1] for r in rows}
    assert "research_run_id" in cols


def test_research_run_id_migration_idempotent(db: ChatDatabase) -> None:
    """Running _init_db twice does not raise (column already exists)."""
    db._init_db()
    db._init_db()
    with sqlite3.connect(db.db_path) as conn:
        rows = conn.execute("PRAGMA table_info(chat_messages)").fetchall()
    assert sum(1 for r in rows if r[1] == "research_run_id") == 1


def test_save_chat_message_with_research_run_id(db: ChatDatabase) -> None:
    """save_chat_message persists research_run_id field."""
    sid = db.create_chat_session()
    db.save_chat_message({
        "session_id": sid,
        "role": "assistant",
        "content": "研究已启动",
        "tool_calls": None,
        "research_run_id": "wf_2026-06-16T02-39-40_20517bd2",
    })
    msgs = db.get_chat_messages(sid)
    assert len(msgs) == 1
    assert msgs[0]["research_run_id"] == "wf_2026-06-16T02-39-40_20517bd2"


def test_save_chat_message_without_research_run_id(db: ChatDatabase) -> None:
    """Missing research_run_id → stored as NULL, no crash."""
    sid = db.create_chat_session()
    db.save_chat_message({
        "session_id": sid,
        "role": "assistant",
        "content": "ordinary reply",
    })
    msgs = db.get_chat_messages(sid)
    assert len(msgs) == 1
    assert msgs[0]["research_run_id"] is None


def test_save_chat_message_with_explicit_none_research_run_id(db: ChatDatabase) -> None:
    """Explicit None research_run_id → NULL column."""
    sid = db.create_chat_session()
    db.save_chat_message({
        "session_id": sid,
        "role": "assistant",
        "content": "hi",
        "research_run_id": None,
    })
    msgs = db.get_chat_messages(sid)
    assert msgs[0]["research_run_id"] is None


def test_get_chat_messages_includes_research_run_id_field(db: ChatDatabase) -> None:
    """The returned dict must include the key (even when NULL) so the
    frontend TS type `research_run_id?: string | null` is satisfied."""
    sid = db.create_chat_session()
    db.save_chat_message({
        "session_id": sid, "role": "user", "content": "/study 量化",
    })
    msgs = db.get_chat_messages(sid)
    assert "research_run_id" in msgs[0]
    assert msgs[0]["research_run_id"] is None


def test_multiple_messages_different_research_run_ids(db: ChatDatabase) -> None:
    """Two /study in one session → two distinct run_ids, each on its own message."""
    sid = db.create_chat_session()
    db.save_chat_message({
        "session_id": sid, "role": "user", "content": "/study 量化",
    })
    db.save_chat_message({
        "session_id": sid, "role": "assistant", "content": "研究已启动",
        "research_run_id": "wf_run_1",
    })
    db.save_chat_message({
        "session_id": sid, "role": "user", "content": "/study 期货",
    })
    db.save_chat_message({
        "session_id": sid, "role": "assistant", "content": "研究已启动",
        "research_run_id": "wf_run_2",
    })
    msgs = db.get_chat_messages(sid)
    assert len(msgs) == 4
    # The two /study commands each produce a distinct run_id; user
    # messages have no run_id. We don't assert specific index order
    # because save_chat_message uses datetime('now') (second precision)
    # and all 4 messages can share a created_at in rapid succession.
    run_ids_by_content = {
        m["content"]: m.get("research_run_id") for m in msgs
    }
    assert run_ids_by_content["/study 量化"] is None
    assert run_ids_by_content["/study 期货"] is None
    # Both assistant messages should have distinct run_ids (order-agnostic)
    run_ids = {m["research_run_id"] for m in msgs if m["role"] == "assistant"}
    assert run_ids == {"wf_run_1", "wf_run_2"}
