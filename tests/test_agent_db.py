"""Tests for AgentDatabase data management methods."""

import json
import logging
import pytest
from pathlib import Path
from llmwikify.agent.backend.db import AgentDatabase


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def db(tmp_path):
    """Create a temporary AgentDatabase."""
    return AgentDatabase(tmp_path / "test_agent.db")


@pytest.fixture
def db_with_data(db):
    """Create a database with test data for wiki_id='test_wiki'."""
    # Chat sessions
    session1 = db.create_session(wiki_id="test_wiki")
    session2 = db.create_session(wiki_id="test_wiki")
    session3 = db.create_session(wiki_id="other_wiki")

    # Messages
    db.save_message({"id": "msg1", "session_id": session1, "role": "user", "content": "Hello"})
    db.save_message({"id": "msg2", "session_id": session1, "role": "assistant", "content": "Hi"})

    # Tool calls
    db.log_tool_call(session1, "search", {"query": "test"})
    db.update_tool_call(
        db.get_tool_calls(session1)[0]["id"],
        {"result": "ok"},
        "done",
    )

    # Research sessions
    rs1 = db.create_research_session("test_wiki", "Test query 1")
    rs2 = db.create_research_session("test_wiki", "Test query 2")
    rs3 = db.create_research_session("other_wiki", "Other query")

    # Research sources
    db.save_source(rs1, "sq1", "web", "http://example.com", "Source 1", 100)
    db.save_source(rs1, "sq2", "web", "http://example2.com", "Source 2", 200)

    # Ingest log
    db.log_ingest({
        "id": "ingest1",
        "wiki_id": "test_wiki",
        "tool": "wiki_ingest",
        "arguments": {"source": "test.md"},
        "status": "ok",
    })

    # Dream proposals
    db.save_proposal({
        "id": "prop1",
        "wiki_id": "test_wiki",
        "page_name": "Test Page",
        "edit_type": "create",
        "content": "content",
        "status": "pending",
    })

    # Notifications
    db.save_notification({
        "id": "notif1",
        "wiki_id": "test_wiki",
        "type": "info",
        "message": "Test notification",
    })

    # Confirmations
    db.save_confirmation({
        "id": "conf1",
        "wiki_id": "test_wiki",
        "tool": "write_page",
        "arguments": {"page_name": "test"},
        "action_type": "write",
        "impact": "low",
        "status": "pending",
    })

    return db, session1, session2, session3, rs1, rs2, rs3


# ==============================================================================
# 1. get_wiki_stats tests
# ==============================================================================

class TestGetWikiStats:
    def test_returns_zero_for_nonexistent_wiki(self, db):
        stats = db.get_wiki_stats("nonexistent")
        assert stats["wiki_id"] == "nonexistent"
        assert stats["chat_sessions"] == 0
        assert stats["research_sessions"] == 0
        assert stats["research_sources"] == 0

    def test_counts_chat_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_wiki_stats("test_wiki")
        assert stats["chat_sessions"] == 2

    def test_counts_research_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_wiki_stats("test_wiki")
        assert stats["research_sessions"] == 2

    def test_counts_research_sources(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_wiki_stats("test_wiki")
        assert stats["research_sources"] == 2

    def test_excludes_other_wikis(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_wiki_stats("other_wiki")
        assert stats["chat_sessions"] == 1
        assert stats["research_sessions"] == 1
        assert stats["research_sources"] == 0


# ==============================================================================
# 2. list_all_wikis tests
# ==============================================================================

class TestListAllWikis:
    def test_empty_database(self, db):
        wikis = db.list_all_wikis()
        assert wikis == []

    def test_lists_all_wikis(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        wikis = db.list_all_wikis()
        wiki_ids = [w["wiki_id"] for w in wikis]
        assert "test_wiki" in wiki_ids
        assert "other_wiki" in wiki_ids

    def test_wiki_stats_included(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        wikis = db.list_all_wikis()
        test_wiki = next(w for w in wikis if w["wiki_id"] == "test_wiki")
        assert test_wiki["chat_sessions"] == 2
        assert test_wiki["research_sessions"] == 2
        assert test_wiki["research_sources"] == 2

    def test_returns_sorted_by_wiki_id(self, db):
        db.create_session(wiki_id="zzz")
        db.create_session(wiki_id="aaa")
        db.create_session(wiki_id="mmm")
        wikis = db.list_all_wikis()
        wiki_ids = [w["wiki_id"] for w in wikis]
        assert wiki_ids == ["aaa", "mmm", "zzz"]


# ==============================================================================
# 3. delete_wiki_data tests
# ==============================================================================

class TestDeleteWikiData:
    def test_returns_zeros_for_nonexistent_wiki(self, db):
        result = db.delete_wiki_data("nonexistent")
        assert result["chat_sessions"] == 0
        assert result["research_sessions"] == 0
        assert result["tool_calls"] == 0
        assert result["ingest_log"] == 0

    def test_deletes_chat_sessions(self, db_with_data):
        db, session1, session2, _, _, _, _ = db_with_data
        result = db.delete_wiki_data("test_wiki")
        assert result["chat_sessions"] == 2
        assert db.get_session(session1) is None
        assert db.get_session(session2) is None

    def test_deletes_research_sessions(self, db_with_data):
        db, _, _, _, rs1, rs2, _ = db_with_data
        result = db.delete_wiki_data("test_wiki")
        assert result["research_sessions"] == 2
        # Verify sources are also deleted (cascade via session_id)
        assert db.get_sources(rs1) == []

    def test_deletes_ingest_log(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        result = db.delete_wiki_data("test_wiki")
        assert result["ingest_log"] == 1
        log = db.get_ingest_log("test_wiki")
        assert len(log) == 0

    def test_preserves_other_wikis(self, db_with_data):
        db, _, _, session3, _, _, _ = db_with_data
        db.delete_wiki_data("test_wiki")
        session = db.get_session(session3)
        assert session is not None
        assert session["wiki_id"] == "other_wiki"

    def test_preserves_other_wiki_research(self, db_with_data):
        db, _, _, _, _, _, rs3 = db_with_data
        db.delete_wiki_data("test_wiki")
        sources = db.get_sources(rs3)
        assert len(sources) == 0  # rs3 has no sources, but session should exist
        # Verify research session exists
        with db._connect() as conn:
            row = conn.execute("SELECT * FROM research_sessions WHERE id = ?", (rs3,)).fetchone()
            assert row is not None


# ==============================================================================
# 4. export_wiki_data tests
# ==============================================================================

class TestExportWikiData:
    def test_returns_empty_for_nonexistent_wiki(self, db):
        data = db.export_wiki_data("nonexistent")
        assert data["chat_sessions"] == []
        assert data["chat_messages"] == []
        assert data["research_sessions"] == []
        assert data["research_sources"] == []
        assert data["research_sub_queries"] == []
        assert data["tool_calls"] == []

    def test_excludes_jwt_token(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        for session in data["chat_sessions"]:
            assert "jwt_token" not in session

    def test_includes_chat_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        assert len(data["chat_sessions"]) == 2

    def test_includes_chat_messages(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        assert len(data["chat_messages"]) >= 2

    def test_includes_research_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        assert len(data["research_sessions"]) == 2

    def test_includes_research_sources(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        assert len(data["research_sources"]) == 2

    def test_includes_tool_calls(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        assert len(data["tool_calls"]) >= 1

    def test_excludes_other_wikis(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("other_wiki")
        for session in data["chat_sessions"]:
            assert session["wiki_id"] == "other_wiki"
        assert len(data["chat_sessions"]) == 1

    def test_json_serializable(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        data = db.export_wiki_data("test_wiki")
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0


# ==============================================================================
# 5. get_db_stats tests
# ==============================================================================

class TestGetDbStats:
    def test_returns_size_info(self, db):
        stats = db.get_db_stats()
        assert stats["size_bytes"] > 0
        assert stats["size_mb"] > 0

    def test_returns_tables_dict(self, db):
        stats = db.get_db_stats()
        assert "tables" in stats
        assert isinstance(stats["tables"], dict)

    def test_counts_chat_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_db_stats()
        assert stats["tables"]["chat_sessions"] == 3

    def test_counts_research_sessions(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_db_stats()
        assert stats["tables"]["research_sessions"] == 3

    def test_counts_research_sources(self, db_with_data):
        db, _, _, _, _, _, _ = db_with_data
        stats = db.get_db_stats()
        assert stats["tables"]["research_sources"] == 2


# ==============================================================================
# 6. _check_db_size tests
# ==============================================================================

class TestCheckDbSize:
    def test_logs_debug_for_small_db(self, db, caplog):
        with caplog.at_level(logging.DEBUG):
            db._check_db_size()
        assert "Agent DB size" in caplog.text

    def test_no_warning_for_small_db(self, db, caplog):
        with caplog.at_level(logging.WARNING):
            db._check_db_size()
        assert "WARNING" not in caplog.text


# ==============================================================================
# 7. Edge cases
# ==============================================================================

class TestEdgeCases:
    def test_delete_cascades_messages(self, db):
        session = db.create_session(wiki_id="test_wiki")
        db.save_message({"id": "m1", "session_id": session, "role": "user", "content": "Test"})
        db.save_message({"id": "m2", "session_id": session, "role": "assistant", "content": "Reply"})
        db.delete_wiki_data("test_wiki")
        messages = db.get_messages(session)
        assert len(messages) == 0

    def test_delete_cascades_tool_calls(self, db):
        session = db.create_session(wiki_id="test_wiki")
        db.log_tool_call(session, "test_tool", {})
        db.delete_wiki_data("test_wiki")
        tool_calls = db.get_tool_calls(session)
        assert len(tool_calls) == 0

    def test_delete_cascades_research_sources(self, db):
        rs = db.create_research_session("test_wiki", "query")
        db.save_source(rs, "sq1", "web", "http://example.com", "Title", 100)
        db.delete_wiki_data("test_wiki")
        sources = db.get_sources(rs)
        assert len(sources) == 0

    def test_delete_cascades_research_sub_queries(self, db):
        rs = db.create_research_session("test_wiki", "query")
        db.save_sub_query(rs, "sub query", "web")
        db.delete_wiki_data("test_wiki")
        sub_queries = db.get_sub_queries(rs)
        assert len(sub_queries) == 0

    def test_multiple_wikis_independent(self, db):
        s1 = db.create_session(wiki_id="wiki_a")
        s2 = db.create_session(wiki_id="wiki_b")
        db.save_message({"id": "m1", "session_id": s1, "role": "user", "content": "A"})
        db.save_message({"id": "m2", "session_id": s2, "role": "user", "content": "B"})

        db.delete_wiki_data("wiki_a")

        assert db.get_session(s1) is None
        assert db.get_session(s2) is not None
        messages = db.get_messages(s2)
        assert len(messages) == 1

    def test_wiki_id_with_special_chars(self, db):
        wiki_id = "my-wiki_v2.0"
        db.create_session(wiki_id=wiki_id)
        stats = db.get_wiki_stats(wiki_id)
        assert stats["chat_sessions"] == 1

        result = db.delete_wiki_data(wiki_id)
        assert result["chat_sessions"] == 1
