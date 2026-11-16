"""Tests for foundation.auth.share — share_tokens table (P6 / Q5=a)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault(
    "LLMWIKIFY_HOME", tempfile.mkdtemp(prefix="llmwikify_share_test_")
)

from llmwikify.foundation.auth import (  # noqa: E402
    AuthError,
    ShareTokenRepository,
    UserRepository,
)


@pytest.fixture()
def repo(tmp_path: Path):
    """ShareTokenRepository on a fresh db with one creator user."""
    db = tmp_path / "share.db"
    users = UserRepository(db_path=db)
    creator = users.create(email="owner@e.com", is_first_admin=True)
    r = ShareTokenRepository(db_path=db)
    return r, creator


class TestSchema:
    def test_table_created(self, repo):
        r, _ = repo
        tables = {
            row["name"]
            for row in r._connect().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "share_tokens" in tables

    def test_schema_ready_skips_rework(self, tmp_path: Path):
        db = tmp_path / "m3.db"
        ShareTokenRepository(db_path=db)
        r2 = ShareTokenRepository(db_path=db)
        assert r2._schema_ready() is True


class TestShareTokenLifecycle:
    def test_create_and_get(self, repo):
        r, creator = repo
        st = r.create(
            wiki_id="wiki-a",
            created_by=creator.id,
            token_hash="hash-abc",
        )
        assert st.wiki_id == "wiki-a"
        assert st.revoked_at is None
        assert st.expires_at is None
        assert st.view_count == 0

        got = r.get_by_id(st.id)
        assert got is not None and got.id == st.id
        by_hash = r.get_by_hash("hash-abc")
        assert by_hash is not None and by_hash.id == st.id

    def test_duplicate_hash(self, repo):
        r, creator = repo
        r.create(wiki_id="w", created_by=creator.id, token_hash="dup")
        with pytest.raises(AuthError) as exc:
            r.create(wiki_id="w", created_by=creator.id, token_hash="dup")
        assert exc.value.code == "share_exists"

    def test_validation(self, repo):
        r, creator = repo
        with pytest.raises(AuthError):
            r.create(wiki_id="", created_by=creator.id, token_hash="x")
        with pytest.raises(AuthError):
            r.create(wiki_id="w", created_by=creator.id, token_hash="")

    def test_revoke_idempotent(self, repo):
        r, creator = repo
        st = r.create(wiki_id="w", created_by=creator.id, token_hash="rev")
        assert r.revoke(st.id) is True
        assert r.revoke(st.id) is False
        # Revoked → get_by_hash misses it.
        assert r.get_by_hash("rev") is None
        # But get_by_id still sees it (audit trail).
        got = r.get_by_id(st.id)
        assert got is not None and got.revoked_at is not None

    def test_expiry(self, repo):
        r, creator = repo
        # Already expired (epoch in the past).
        r.create(
            wiki_id="w",
            created_by=creator.id,
            token_hash="expired",
            expires_at="1",
        )
        assert r.get_by_hash("expired") is None
        # Far future.
        r.create(
            wiki_id="w",
            created_by=creator.id,
            token_hash="future",
            expires_at="9999999999",
        )
        assert r.get_by_hash("future") is not None

    def test_touch_view(self, repo):
        r, creator = repo
        st = r.create(wiki_id="w", created_by=creator.id, token_hash="view")
        r.touch_view(st.id)
        r.touch_view(st.id)
        got = r.get_by_id(st.id)
        assert got is not None
        assert got.view_count == 2
        assert got.last_viewed_at is not None

    def test_list_filters(self, repo):
        r, creator = repo
        r.create(wiki_id="a", created_by=creator.id, token_hash="h1")
        r.create(wiki_id="b", created_by=creator.id, token_hash="h2")
        second = r.create(wiki_id="a", created_by=creator.id, token_hash="h3")
        r.revoke(second.id)

        assert len(r.list()) == 2  # revoked excluded by default
        assert len(r.list(include_revoked=True)) == 3
        assert len(r.list(wiki_id="a")) == 1
        assert len(r.list(wiki_id="a", include_revoked=True)) == 2
        assert len(r.list(created_by=creator.id, include_revoked=True)) == 3
