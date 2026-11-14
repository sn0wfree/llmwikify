"""Tests for foundation.auth.grants — wiki_grants / groups / group_members (P1).

Decisions exercised:
  - D1 flat principal×wiki×r/w (no role layer)
  - D3 wiki-level (no page_id)
  - D4 read/write only
  - D5 no deny rows; revoke = delete
  - D9 'public' principal row
  - Q1 group support
  - Q3 wildcard: table allows '*', snapshots expand to concrete ids
  - M1 WAL / M2 connection reuse / M3 schema-once
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Force a temp home BEFORE importing auth so auth_db_path is isolated.
os.environ.setdefault(
    "LLMWIKIFY_HOME", tempfile.mkdtemp(prefix="llmwikify_grants_test_")
)

from llmwikify.foundation.auth import (  # noqa: E402
    PRINCIPAL_TYPES,
    WILDCARD,
    ApiKeyRepository,
    AuthError,
    GrantRepository,
    UserRepository,
)


@pytest.fixture(autouse=True)
def _fresh_home(monkeypatch, tmp_path):
    monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
    yield


class TestSchema:
    def test_tables_created(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g.db")
        tables = {
            r["name"]
            for r in repo._connect().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"wiki_grants", "groups", "group_members"} <= tables

    def test_wal_mode_enabled_m1(self, tmp_path: Path) -> None:
        """M1: auth.db runs in WAL so readers don't block writers."""
        repo = GrantRepository(db_path=tmp_path / "wal.db")
        mode = repo._connect().execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"

    def test_auth_repos_share_wal_connection_m2(self, tmp_path: Path) -> None:
        """M2: same path → same thread-local connection (no per-call connect)."""
        db = tmp_path / "share.db"
        u = UserRepository(db_path=db)
        a = ApiKeyRepository(db_path=db)
        g = GrantRepository(db_path=db)
        assert u._connect() is a._connect() is g._connect()

    def test_connection_reused_across_calls_m2(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "reuse.db")
        assert repo._connect() is repo._connect()

    def test_schema_ready_skips_rework_m3(self, tmp_path: Path) -> None:
        db = tmp_path / "m3.db"
        repo = GrantRepository(db_path=db)
        assert repo._schema_ready() is True
        # Re-instantiating on the same path must not re-run executescript.
        repo2 = GrantRepository(db_path=db)
        assert repo2._schema_ready() is True


class TestGrantLifecycle:
    def test_grant_and_effective(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "e.db")
        repo.grant("user", "u1", "wiki-a", read=True)
        assert repo.effective("u1", "wiki-a") == (True, False)
        repo.grant("user", "u1", "wiki-a", write=True)
        # write implies read
        assert repo.effective("u1", "wiki-a") == (True, True)
        assert repo.effective("u1", "wiki-b") == (False, False)

    def test_grant_is_upsert_not_duplicate(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "u.db")
        repo.grant("user", "u1", "wiki-a", read=True)
        repo.grant("user", "u1", "wiki-a", write=True)
        rows = repo.list_grants(principal_id="u1")
        assert len(rows) == 1
        assert rows[0]["can_write"] == 1

    def test_revoke_deletes_row_d5(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "r.db")
        repo.grant("user", "u1", "wiki-a", write=True)
        assert repo.revoke("user", "u1", "wiki-a") is True
        assert repo.effective("u1", "wiki-a") == (False, False)
        # Second revoke is a no-op.
        assert repo.revoke("user", "u1", "wiki-a") is False
        # No deny rows ever exist.
        rows = repo.list_grants()
        assert all(r["can_read"] >= 0 and r["can_write"] >= 0 for r in rows)

    def test_invalid_principal_type(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "v.db")
        with pytest.raises(AuthError) as exc:
            repo.grant("robot", "x", "wiki-a", read=True)
        assert exc.value.code == "invalid_principal"
        assert set(PRINCIPAL_TYPES) == {"user", "group", "public"}


class TestWildcardQ3:
    def test_wildcard_covers_every_wiki(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "w.db")
        repo.grant("user", "u1", WILDCARD, read=True)
        assert repo.effective("u1", "wiki-a") == (True, False)
        assert repo.effective("u1", "wiki-zzz") == (True, False)  # future wiki

    def test_wildcard_unions_with_explicit(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "w2.db")
        repo.grant("user", "u1", WILDCARD, read=True)
        repo.grant("user", "u1", "wiki-a", write=True)
        # wiki-a: read (wildcard) ∪ write (explicit) = rw
        assert repo.effective("u1", "wiki-a") == (True, True)
        # other wikis: read only
        assert repo.effective("u1", "wiki-b") == (True, False)

    def test_expand_never_returns_wildcard_q3b(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "w3.db")
        repo.grant("user", "u1", WILDCARD, write=True)
        # At signing time only these wikis are known:
        snapshot = repo.expand("u1", ["wiki-a", "wiki-b"])
        assert WILDCARD not in snapshot
        assert set(snapshot) == {"wiki-a", "wiki-b"}
        assert all(v == (True, True) for v in snapshot.values())
        # A wiki created after signing is NOT in the snapshot (Q3-b) …
        assert "wiki-new" not in snapshot
        # …but the live upper bound does cover it (Q3-c).
        assert repo.effective("u1", "wiki-new") == (True, True)

    def test_expand_respects_explicit_over_wildcard(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "w4.db")
        repo.grant("user", "u1", WILDCARD, read=True)
        repo.grant("user", "u1", "wiki-a", write=True)
        out = repo.expand("u1", ["wiki-a", "wiki-b"])
        assert out["wiki-a"] == (True, True)
        assert out["wiki-b"] == (True, False)


class TestGroupsQ1:
    def test_group_grant_applies_to_members(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g1.db")
        gid = repo.create_group("team")
        repo.add_member(gid, "u1")
        repo.add_member(gid, "u2")
        repo.grant("group", gid, "wiki-a", write=True)
        assert repo.effective("u1", "wiki-a") == (True, True)
        assert repo.effective("u2", "wiki-a") == (True, True)
        assert repo.effective("u3", "wiki-a") == (False, False)

    def test_group_membership_is_idempotent(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g2.db")
        gid = repo.create_group("t")
        assert repo.add_member(gid, "u1") is True
        assert repo.add_member(gid, "u1") is False
        assert repo.list_members(gid) == ["u1"]

    def test_remove_member_revokes_immediately(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g3.db")
        gid = repo.create_group("t")
        repo.add_member(gid, "u1")
        repo.grant("group", gid, "wiki-a", read=True)
        assert repo.effective("u1", "wiki-a") == (True, False)
        repo.remove_member(gid, "u1")
        assert repo.effective("u1", "wiki-a") == (False, False)

    def test_duplicate_group_name(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g4.db")
        repo.create_group("dup")
        with pytest.raises(AuthError) as exc:
            repo.create_group("dup")
        assert exc.value.code == "group_exists"

    def test_groups_of(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "g5.db")
        a = repo.create_group("a")
        b = repo.create_group("b")
        repo.add_member(a, "u1")
        repo.add_member(b, "u1")
        assert set(repo.groups_of("u1")) == {a, b}
        assert repo.groups_of("u2") == []


class TestPublicPrincipalD9:
    def test_public_row_applies_to_unauthenticated(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "p.db")
        repo.grant("public", WILDCARD, "wiki-a", read=True)
        # Unauthenticated (user_id=None) sees the public grant.
        assert repo.effective(None, "wiki-a") == (True, False)
        # Authenticated users see it too (additive).
        assert repo.effective("u1", "wiki-a") == (True, False)

    def test_public_requires_wildcard_id(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "p2.db")
        with pytest.raises(AuthError):
            repo.grant("public", "something", "wiki-a", read=True)


class TestValidation:
    def test_empty_wiki_id(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "x.db")
        with pytest.raises(AuthError) as exc:
            repo.grant("user", "u1", "", read=True)
        assert exc.value.code == "invalid_wiki"

    def test_empty_principal_id(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "x2.db")
        with pytest.raises(AuthError):
            repo.grant("user", "", "wiki-a", read=True)

    def test_list_grants_filters(self, tmp_path: Path) -> None:
        repo = GrantRepository(db_path=tmp_path / "x3.db")
        repo.grant("user", "u1", "wiki-a", read=True)
        repo.grant("group", "g1", "wiki-b", read=True)
        assert len(repo.list_grants(principal_type="user")) == 1
        assert len(repo.list_grants(principal_id="g1")) == 1
        assert len(repo.list_grants()) == 2
