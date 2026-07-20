"""Tests for ChatSessionRepository (chat_sessions table)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ChatSessionRepository


@pytest.fixture
def repo(tmp_path: Path) -> ChatSessionRepository:
    """Create a repo backed by a tmpdir SQLite file.

    The repo's schema is initialized explicitly because each
    repository is meant to be standalone (its schema is run by
    ChatDatabase._init_db in production, but in tests we go direct).
    """
    r = ChatSessionRepository(tmp_path / "test.db")
    r._init_schema()
    return r


# ─── create_chat_session ────────────────────────────────────────


class TestCreate:
    def test_returns_uuid_hex(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        assert isinstance(sid, str)
        assert len(sid) == 32  # uuid4 hex
        # Persisted
        assert repo.get_chat_session(sid) is not None

    def test_creates_with_wiki_id(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session(wiki_id="wiki-1")
        session = repo.get_chat_session(sid)
        assert session["wiki_id"] == "wiki-1"

    def test_creates_with_wiki_id_only(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session(wiki_id="w")
        session = repo.get_chat_session(sid)
        assert session["wiki_id"] == "w"
        # JWT token is NOT stored (security: removed in v0.40)

    def test_jwt_token_not_stored(self, repo: ChatSessionRepository) -> None:
        """JWT tokens are NOT persisted to chat_sessions (security).

        The session is bound to a wiki + client identity, not to
        a long-lived JWT. Tokens are validated per-request and
        never stored.
        """
        sid = repo.create_chat_session(wiki_id="w")
        session = repo.get_chat_session(sid)
        assert "jwt_token" not in session or session.get("jwt_token") is None

    def test_two_creates_have_different_ids(self, repo: ChatSessionRepository) -> None:
        a = repo.create_chat_session()
        b = repo.create_chat_session()
        assert a != b


# ─── get / update / list ────────────────────────────────────────


class TestGetUpdate:
    def test_get_missing_returns_none(self, repo: ChatSessionRepository) -> None:
        assert repo.get_chat_session("nonexistent") is None

    def test_update_wiki_changes_field(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        repo.update_chat_session_wiki(sid, "new-wiki")
        assert repo.get_chat_session(sid)["wiki_id"] == "new-wiki"

    def test_update_title(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        repo.update_chat_session_title(sid, "My Chat")
        assert repo.get_chat_session(sid)["title"] == "My Chat"

    def test_update_bumps_updated_at(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        before = repo.get_chat_session(sid)["updated_at"]
        repo.update_chat_session_title(sid, "x")
        after = repo.get_chat_session(sid)["updated_at"]
        assert after >= before


class TestList:
    def test_list_empty(self, repo: ChatSessionRepository) -> None:
        assert repo.list_chat_sessions() == []

    def test_list_returns_all_newest_first(self, repo: ChatSessionRepository) -> None:
        a = repo.create_chat_session(wiki_id="a")
        b = repo.create_chat_session(wiki_id="b")
        c = repo.create_chat_session(wiki_id="c")
        sessions = repo.list_chat_sessions()
        assert len(sessions) == 3
        # All 3 ids must be present. ORDER BY created_at DESC may
        # tie for sub-second inserts (datetime('now') has second
        # precision), so we don't assert strict order.
        ids = {s["id"] for s in sessions}
        assert ids == {a, b, c}


# ─── delete_chat_session ────────────────────────────────────────


class TestDelete:
    def test_delete_returns_true_when_row_exists(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        assert repo.delete_chat_session(sid) is True
        assert repo.get_chat_session(sid) is None

    def test_delete_returns_false_when_missing(self, repo: ChatSessionRepository) -> None:
        assert repo.delete_chat_session("nonexistent") is False

    def test_delete_does_not_touch_other_tables(
        self, repo: ChatSessionRepository, tmp_path: Path,
    ) -> None:
        """delete_chat_session only deletes from chat_sessions;
        cascade is the facade's responsibility.

        Note: by default PRAGMA foreign_keys = ON would block
        deleting a session that has child tool_calls rows. We
        disable FKs for this test to verify the repo layer does
        NOT auto-cascade (the facade does manual cascade).
        """
        from llmwikify.apps.chat.db import ToolCallRepository
        db_path = tmp_path / "test.db"
        repo._mgr.conn.execute("PRAGMA foreign_keys = OFF")
        tools = ToolCallRepository(db_path)
        tools._init_schema()
        sid = repo.create_chat_session()
        tools.log_tool_call(sid, "echo", {"x": 1})
        # Delete just the session row via the repo
        assert repo.delete_chat_session(sid) is True
        # tool_calls row still exists (cascade is facade's job)
        # because FK is OFF and the repo doesn't manually cascade
        assert tools.get_tool_calls(sid) != []


# ─── get_chat_session_title ─────────────────────────────────────


class TestTitle:
    def test_missing_session_returns_empty(self, repo: ChatSessionRepository) -> None:
        assert repo.get_chat_session_title("nonexistent") == ""

    def test_stored_title_returned(self, repo: ChatSessionRepository) -> None:
        sid = repo.create_chat_session()
        repo.update_chat_session_title(sid, "My Title")
        assert repo.get_chat_session_title(sid) == "My Title"

    def test_no_title_returns_empty(self, repo: ChatSessionRepository) -> None:
        """Empty title + no fallback derivation returns empty string."""
        sid = repo.create_chat_session()
        # Repo itself does not derive from messages (facade does)
        assert repo.get_chat_session_title(sid) == ""
