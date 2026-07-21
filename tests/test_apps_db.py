"""Tests for AppDatabase (apps/db.py) — 3-facade aggregate."""

from __future__ import annotations

import tempfile

import pytest

from llmwikify.apps.chat.db import ChatDatabase
from llmwikify.apps.db import AppDatabase
from llmwikify.apps.research.db import ResearchDatabase
from llmwikify.apps.wiki.db import WikiDatabase


@pytest.fixture
def app_db():
    with tempfile.TemporaryDirectory() as tmp:
        yield AppDatabase(tmp)


class TestAppDatabaseInit:
    def test_creates_all_three_facades(self, app_db: AppDatabase) -> None:
        assert isinstance(app_db.chat, ChatDatabase)
        assert isinstance(app_db.research, ResearchDatabase)
        assert isinstance(app_db.wiki, WikiDatabase)

    def test_shared_db_path(self, app_db: AppDatabase) -> None:
        assert app_db.db_path == app_db.chat.db_path
        assert app_db.db_path == app_db.research.db_path
        assert app_db.db_path == app_db.wiki.db_path

    def test_shared_data_dir(self, app_db: AppDatabase) -> None:
        assert app_db.data_dir == app_db.chat.data_dir

    def test_db_path_is_llmwiki_agent(self, app_db: AppDatabase) -> None:
        assert app_db.db_path.name == ".llmwiki_agent.db"


class TestAppDatabaseOperations:
    def test_chat_operations(self, app_db: AppDatabase) -> None:
        sid = app_db.chat.create_chat_session("wiki-1")
        assert sid
        session = app_db.chat.get_chat_session(sid)
        assert session is not None
        assert session["wiki_id"] == "wiki-1"

    def test_research_operations(self, app_db: AppDatabase) -> None:
        sid = app_db.research.create_research_session("wiki-1", "test query")
        assert sid
        session = app_db.research.get_research_session(sid)
        assert session is not None
        assert session["query"] == "test query"

    def test_wiki_operations(self, app_db: AppDatabase) -> None:
        app_db.wiki.save_notification({
            "wiki_id": "wiki-1",
            "type": "info",
            "message": "test",
        })
        notifs = app_db.wiki.list_notifications("wiki-1")
        assert len(notifs) == 1

    def test_cross_facade_independence(self, app_db: AppDatabase) -> None:
        """Each facade only sees its own domain tables."""
        import sqlite3
        with sqlite3.connect(app_db.db_path) as conn:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        # ChatDatabase tables
        assert "chat_sessions" in tables
        assert "chat_messages" in tables
        assert "tool_calls" in tables
        assert "context_entries" in tables
        # ResearchDatabase tables
        assert "autoresearch_sessions" in tables
        assert "research_steps" in tables
        # WikiDatabase tables
        assert "dream_proposals" in tables
        assert "notifications" in tables
        assert "confirmations" in tables
        assert "ingest_log" in tables


class TestAppDatabaseIdempotent:
    def test_re_instantiation_preserves_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db1 = AppDatabase(tmp)
            sid = db1.chat.create_chat_session("wiki-1")
            db2 = AppDatabase(tmp)
            session = db2.chat.get_chat_session(sid)
            assert session is not None


class TestWikiDatabaseGetConfirmationDecoded:
    def test_returns_none_for_missing(self, app_db: AppDatabase) -> None:
        assert app_db.wiki.get_confirmation_with_decoded_args("nope") is None

    def test_decodes_arguments_from_json_string(self, app_db: AppDatabase) -> None:
        app_db.wiki.save_confirmation({
            "id": "abc12345",
            "wiki_id": "wiki-1",
            "tool": "wiki_page_update",
            "arguments": {"page_name": "test", "expires_at": 9999999999.0},
            "status": "pending",
        })
        conf = app_db.wiki.get_confirmation_with_decoded_args("abc12345")
        assert conf is not None
        assert conf["arguments"] == {"page_name": "test", "expires_at": 9999999999.0}
        assert isinstance(conf["arguments"], dict)

    def test_returns_copy_not_mutation(self, app_db: AppDatabase) -> None:
        app_db.wiki.save_confirmation({
            "id": "abc12345",
            "wiki_id": "wiki-1",
            "tool": "wiki_page_update",
            "arguments": {"page_name": "test"},
            "status": "pending",
        })
        conf = app_db.wiki.get_confirmation_with_decoded_args("abc12345")
        assert conf["arguments"]["page_name"] == "test"
        conf["arguments"]["page_name"] = "mutated"
        raw = app_db.wiki.get_confirmation("abc12345")
        assert isinstance(raw["arguments"], str)

    def test_returns_dict_unchanged_when_already_decoded(self, app_db: AppDatabase) -> None:
        app_db.wiki.save_confirmation({
            "id": "abc12345",
            "wiki_id": "wiki-1",
            "tool": "wiki_page_update",
            "arguments": {"page_name": "test"},
            "status": "pending",
        })
        conf = app_db.wiki.get_confirmation_with_decoded_args("abc12345")
        assert isinstance(conf["arguments"], dict)
        assert conf["arguments"]["page_name"] == "test"

    def test_returns_raw_on_json_decode_failure(self, app_db: AppDatabase) -> None:
        """Corrupt JSON in arguments → return raw row (arguments stays str)."""
        import sqlite3

        with sqlite3.connect(app_db.db_path) as conn:
            conn.execute(
                """INSERT INTO confirmations
                   (id, wiki_id, tool, arguments, status)
                   VALUES (?, ?, ?, ?, ?)""",
                ("bad12345", "wiki-1", "x", "{not valid json", "pending"),
            )
            conn.commit()
        conf = app_db.wiki.get_confirmation_with_decoded_args("bad12345")
        assert conf is not None
        assert conf["arguments"] == "{not valid json"
        assert isinstance(conf["arguments"], str)
