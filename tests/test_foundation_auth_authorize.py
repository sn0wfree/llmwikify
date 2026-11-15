"""Tests for foundation.auth.authorize — P4a decision function.

Covers the fixed short-circuit order (design §12.5):
  disabled → scope → admin → non-wiki → legacy → live → snapshot.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault(
    "LLMWIKIFY_HOME", tempfile.mkdtemp(prefix="llmwikify_authz_test_")
)

from llmwikify.foundation.auth import (  # noqa: E402
    AuthzDecision,
    GrantRepository,
    TokenClaims,
    UserRepository,
    authorize_request,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """Fresh auth.db with one admin, one user, and some grants."""
    path = tmp_path / "authz.db"
    users = UserRepository(db_path=path)
    users.create(email="admin@e.com", is_first_admin=True)
    user = users.create(email="user@e.com", is_first_admin=False)
    grants = GrantRepository(db_path=path)
    grants.grant("user", user.id, "wiki-r", read=True)
    grants.grant("user", user.id, "wiki-rw", write=True)
    return path


def _claims(
    user_id: str,
    *,
    scope: str = "read",
    wikis: list[str] | None = None,
    wgrants: dict[str, str] | None = None,
) -> TokenClaims:
    return TokenClaims.new(
        sub=f"user:{user_id}",
        scope=scope,
        wikis=wikis if wikis is not None else [],
        wgrants=wgrants if wgrants is not None else {},
    )


class TestSubject:
    def test_share_token_rejected(self):
        c = TokenClaims.new(sub="share:abc", scope="read", wikis=["*"])
        d = authorize_request(c, wiki_id="wiki-a", need_write=False)
        assert d.allowed is False
        assert d.status == 401
        assert d.code == "invalid_subject"


class TestDisabled:
    def test_disabled_user_401(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.create(email="off@e.com")
        users.disable(u.id)
        c = _claims(u.id, wikis=["*"], wgrants={"wiki-a": "rw"})
        d = authorize_request(c, wiki_id="wiki-a", need_write=False, db_path=db)
        assert d.allowed is False
        assert d.status == 401
        assert d.code == "user_disabled"

    def test_missing_user_is_401_p4b(self, db: Path):
        """P4b: a token for a deleted/unknown user → 401 user_not_found."""
        c = _claims("no-such-user", scope="write", wikis=["*"])
        d = authorize_request(c, wiki_id="wiki-a", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.status == 401
        assert d.code == "user_not_found"


class TestScope:
    def test_read_scope_cannot_write(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="read", wgrants={"wiki-rw": "rw"})
        d = authorize_request(c, wiki_id="wiki-rw", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_scope"

    def test_write_scope_can_read(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="write", wgrants={"wiki-r": "r"})
        d = authorize_request(c, wiki_id="wiki-r", need_write=False, db_path=db)
        assert d.allowed is True


class TestAdmin:
    def test_admin_full_access(self, db: Path):
        users = UserRepository(db_path=db)
        admin = users.get_by_email("admin@e.com")
        assert admin is not None
        c = _claims(admin.id, scope="write", wikis=["*"])
        d = authorize_request(c, wiki_id="brand-new", need_write=True, db_path=db)
        assert d.allowed is True

    def test_admin_bypasses_grants_table(self, db: Path):
        """Admin has no grant rows yet still passes (PG owner)."""
        users = UserRepository(db_path=db)
        admin = users.get_by_email("admin@e.com")
        assert admin is not None
        # No grants at all for admin.
        c = _claims(admin.id, scope="write", wikis=["*"])
        assert authorize_request(
            c, wiki_id="anything", need_write=True, db_path=db
        ).allowed is True


class TestNonWikiRoute:
    def test_wiki_id_none_allows_after_scope(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="read")
        d = authorize_request(c, wiki_id=None, need_write=False, db_path=db)
        assert d.allowed is True

    def test_wiki_id_none_still_enforces_scope(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="read")
        d = authorize_request(c, wiki_id=None, need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_scope"


class TestLegacyToken:
    """wgrants empty + wikis non-empty → pre-P3 token; wikis govern."""

    @staticmethod
    def _uid(db: Path) -> str:
        u = UserRepository(db_path=db).get_by_email("user@e.com")
        assert u is not None
        return u.id

    def test_legacy_wildcard_allows_any(self, db: Path):
        c = _claims(self._uid(db), scope="write", wikis=["*"])
        d = authorize_request(c, wiki_id="whatever", need_write=True, db_path=db)
        assert d.allowed is True

    def test_legacy_list_respected(self, db: Path):
        uid = self._uid(db)
        c = _claims(uid, scope="write", wikis=["main"])
        assert authorize_request(
            c, wiki_id="main", need_write=True, db_path=db
        ).allowed is True
        d = authorize_request(c, wiki_id="side", need_write=False, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_wiki"

    def test_legacy_still_bound_by_scope(self, db: Path):
        """Old non-admin tokens keep scope=read — no privilege escalation."""
        c = _claims(self._uid(db), scope="read", wikis=["*"])
        d = authorize_request(c, wiki_id="main", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_scope"


class TestNewTokenLiveAndSnapshot:
    def _user_id(self, db: Path) -> str:
        u = UserRepository(db_path=db).get_by_email("user@e.com")
        assert u is not None
        return u.id

    def test_zero_grants_denied(self, db: Path):
        uid = self._user_id(db)
        # New token shape: empty wgrants AND empty wikis → live check.
        c = _claims(uid, scope="read", wikis=[], wgrants={})
        d = authorize_request(c, wiki_id="wiki-r", need_write=False, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_wiki"

    def test_read_grant_allows_get_denies_post(self, db: Path):
        uid = self._user_id(db)
        c = _claims(uid, scope="read", wikis=["wiki-r"], wgrants={"wiki-r": "r"})
        assert authorize_request(
            c, wiki_id="wiki-r", need_write=False, db_path=db
        ).allowed is True
        # scope=read already blocks write before we reach grants.
        d = authorize_request(c, wiki_id="wiki-r", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_scope"

    def test_write_grant_allows_post(self, db: Path):
        uid = self._user_id(db)
        c = _claims(
            uid, scope="write", wikis=["wiki-rw"], wgrants={"wiki-rw": "rw"}
        )
        d = authorize_request(c, wiki_id="wiki-rw", need_write=True, db_path=db)
        assert d.allowed is True

    def test_write_grant_but_readonly_snapshot_denied(self, db: Path):
        """D7: snapshot is the ceiling — a post-signing write grant is not
        retroactive."""
        uid = self._user_id(db)
        # Live has wiki-rw:rw (granted in fixture); snapshot says "r".
        c = _claims(
            uid, scope="write", wikis=["wiki-rw"], wgrants={"wiki-rw": "r"}
        )
        d = authorize_request(c, wiki_id="wiki-rw", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_wiki"

    def test_wiki_absent_from_snapshot_denied(self, db: Path):
        """Q3-b: a wiki created after signing is not in the snapshot."""
        uid = self._user_id(db)
        grants = GrantRepository(db_path=db)
        grants.grant("user", uid, "*", read=True)  # live covers everything
        c = _claims(
            uid, scope="read", wikis=["wiki-r"], wgrants={"wiki-r": "r"}
        )
        # Live allows (wildcard), snapshot does not contain wiki-new.
        d = authorize_request(c, wiki_id="wiki-new", need_write=False, db_path=db)
        assert d.allowed is False
        assert "snapshot" in d.detail

    def test_revoked_grant_denied_next_request(self, db: Path):
        """D6-A: revoke → the very next authorize call denies."""
        uid = self._user_id(db)
        grants = GrantRepository(db_path=db)
        grants.revoke("user", uid, "wiki-rw")
        c = _claims(
            uid, scope="write", wikis=["wiki-rw"], wgrants={"wiki-rw": "rw"}
        )
        d = authorize_request(c, wiki_id="wiki-rw", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.code == "forbidden_wiki"


class TestFailClosed:
    def test_query_error_denies(self, db: Path, monkeypatch):
        """M4: a grants query failure must deny, never allow."""
        from llmwikify.foundation.auth import grants as grants_mod

        def _boom(*_a, **_k):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(grants_mod.GrantRepository, "effective", _boom)
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="write", wikis=["wiki-rw"], wgrants={"wiki-rw": "rw"})
        d = authorize_request(c, wiki_id="wiki-rw", need_write=True, db_path=db)
        assert d.allowed is False
        assert d.status == 403
        assert d.code == "authz_unavailable"


class TestDecisionShape:
    def test_allow_is_200(self, db: Path):
        users = UserRepository(db_path=db)
        u = users.get_by_email("user@e.com")
        assert u is not None
        c = _claims(u.id, scope="write", wikis=["*"])
        d = authorize_request(c, wiki_id=None, need_write=True, db_path=db)
        assert isinstance(d, AuthzDecision)
        assert d.allowed is True
        assert d.status == 200
