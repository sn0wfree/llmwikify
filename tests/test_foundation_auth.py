"""Tests for foundation.auth — L1 primitives.

Phase 2.5: PAT-only auth (no passwords).
Phase 2a decision 11: auth.db path = ~/.llmwikify/auth.db (override via
    LLMWIKIFY_HOME env var for tests so we never touch the real DB).

These tests do NOT exercise keyring (CI envs may not have a daemon;
the hard-fail behavior is tested separately in test_interfaces_auth.py
via a mocked keyring backend).
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Force a per-test temp home BEFORE importing auth so module-level
# constants (auth_db_path default) don't cache the real path.
TEST_HOME = Path(tempfile.mkdtemp(prefix="llmwikify_auth_test_"))
os.environ["LLMWIKIFY_HOME"] = str(TEST_HOME)

from llmwikify.foundation.auth import (  # noqa: E402
    AuthError,
    TokenClaims,
    auth_db_path,
    auto_first_admin,
    decode,
    encode,
    env_host,
    generate_pat,
    hash_pat,
    is_local_default,
    verify_pat,
)
from llmwikify.foundation.auth.db import (  # noqa: E402
    ApiKey,
    ApiKeyRepository,
    User,
    UserRepository,
)

# ─── is_local_default / env_host ─────────────────────────────────


class TestLocalDefaultDetection:
    """Decisions 12, 13: serve should default to local mode for
    loopback addresses."""

    def test_loopback_v4(self):
        assert is_local_default("127.0.0.1") is True

    def test_loopback_v6(self):
        assert is_local_default("::1") is True

    def test_wildcard_v4_is_not_local(self):
        # 0.0.0.0 = "all interfaces" — must NOT be treated as local
        # (defeating the safety gate).
        assert is_local_default("0.0.0.0") is False

    def test_wildcard_v6_is_not_local(self):
        assert is_local_default("::") is False

    def test_real_lan_ip_is_not_local(self):
        assert is_local_default("192.168.1.5") is False
        assert is_local_default("10.0.0.1") is False

    def test_dns_name_is_not_local(self):
        # Conservative: only exact loopback strings are trusted.
        assert is_local_default("localhost.example.com") is False

    def test_localhost_literal_is_local(self):
        assert is_local_default("localhost") is True

    def test_empty_host_is_local(self):
        # Treat empty/None as "no bind specified" → assume local.
        assert is_local_default("") is True
        assert is_local_default(None) is True

    def test_invalid_string_is_not_local(self):
        assert is_local_default("not-an-ip") is False


class TestEnvHost:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("LLMWIKIFY_HOST", raising=False)
        assert env_host() == "127.0.0.1"

    def test_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("LLMWIKIFY_HOST", "   ")
        assert env_host() == "127.0.0.1"

    def test_explicit_value(self, monkeypatch):
        monkeypatch.setenv("LLMWIKIFY_HOST", "0.0.0.0")
        assert env_host() == "0.0.0.0"


# ─── PAT primitives (decision 25-27) ──────────────────────────────


class TestPAT:
    def test_generate_pat_format(self):
        plain, pat_hash = generate_pat()
        assert plain.startswith("llmw_")
        assert len(plain) == 53  # llmw_ (5) + 48 hex chars (24 bytes)
        assert isinstance(pat_hash, str)
        assert len(pat_hash) == 64  # SHA-256 hex digest

    def test_hash_pat_deterministic(self):
        pat = "llmw_abc123def456"
        h1 = hash_pat(pat)
        h2 = hash_pat(pat)
        assert h1 == h2

    def test_verify_pat_correct(self):
        plain, pat_hash = generate_pat()
        assert verify_pat(pat_hash, plain) is True

    def test_verify_pat_wrong_token(self):
        plain, pat_hash = generate_pat()
        wrong, _ = generate_pat()
        assert verify_pat(pat_hash, wrong) is False

    def test_verify_pat_corrupted_hash(self):
        assert verify_pat("not-a-valid-hash", "anything") is False
        assert verify_pat("a" * 64, "anything") is False

    def test_verify_pat_invalid_input_types(self):
        with pytest.raises(TypeError):
            hash_pat(12345)  # type: ignore[arg-type]
        # verify_pat should not raise, just return False.
        assert verify_pat(12345, "ignored") is False  # type: ignore[arg-type]
        assert verify_pat("ignored", 12345) is False  # type: ignore[arg-type]

    def test_generate_pat_unique_per_call(self):
        p1, h1 = generate_pat()
        p2, h2 = generate_pat()
        assert p1 != p2
        assert h1 != h2


# ─── JWT roundtrip ───────────────────────────────────────────────


class TestJWT:
    def test_basic_roundtrip(self):
        secret = b"x" * 32
        c = TokenClaims.new(sub="user:abc", scope="write", wikis=["main"], ttl_seconds=60)
        token = encode(c, secret)
        c2 = decode(token, secret)
        assert c2.sub == "user:abc"
        assert c2.scope == "write"
        assert c2.wikis == ["main"]
        assert c2.exp - c2.iat == 60

    def test_audience_enforced(self):
        import jwt as pyjwt

        secret = b"x" * 32
        # Manually craft a token with a different aud.
        c = TokenClaims.new(sub="user:abc", scope="read", wikis=["*"], ttl_seconds=60)
        c.aud = "evil-audience"
        token = encode(c, secret)
        with pytest.raises(pyjwt.InvalidAudienceError):
            decode(token, secret)

    def test_expired(self):
        import jwt as pyjwt

        secret = b"x" * 32
        c = TokenClaims(sub="user:abc", scope="read", wikis=["*"], exp=int(time.time()) - 1, iat=0)
        token = encode(c, secret)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode(token, secret)

    def test_bad_signature(self):
        import jwt as pyjwt

        secret1 = b"x" * 32
        secret2 = b"y" * 32
        c = TokenClaims.new(sub="user:abc", scope="read", wikis=["*"], ttl_seconds=60)
        token = encode(c, secret1)
        with pytest.raises(pyjwt.InvalidSignatureError):
            decode(token, secret2)


# ─── UserRepository / auto_first_admin ───────────────────────────


class TestUserRepository:
    def test_schema_creation(self):
        repo = UserRepository(db_path=TEST_HOME / "auth.db")
        assert (TEST_HOME / "auth.db").exists()
        # Just check the table exists.
        for row in repo._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ):
            assert row[0] == "users"

    def test_create_and_get(self):
        repo = UserRepository(db_path=TEST_HOME / "auth2.db")
        user = repo.create(
            email="alice@example.com",
            is_first_admin=True,
        )
        assert user.email == "alice@example.com"
        assert user.is_first_admin is True
        assert user.username is not None
        assert user.username.startswith("alice")

        fetched = repo.get_by_email("alice@example.com")
        assert fetched is not None
        assert fetched.id == user.id

    def test_duplicate_email_raises(self):
        repo = UserRepository(db_path=TEST_HOME / "auth3.db")
        repo.create(email="dup@example.com")
        with pytest.raises(AuthError) as exc_info:
            repo.create(email="dup@example.com")
        assert exc_info.value.code == "email_taken"

    def test_user_has_no_password_hash(self):
        repo = UserRepository(db_path=TEST_HOME / "auth4.db")
        user = repo.create(email="bob@example.com")
        assert user.email == "bob@example.com"
        # User dataclass no longer has password_hash field.
        assert not hasattr(user, "password_hash")

    def test_get_by_id_missing_returns_none(self):
        repo = UserRepository(db_path=TEST_HOME / "auth5.db")
        assert repo.get_by_id("nonexistent") is None

    def test_exists(self):
        repo = UserRepository(db_path=TEST_HOME / "auth6.db")
        assert repo.exists() is False
        repo.create(email="first@example.com")
        assert repo.exists() is True

    def test_touch_last_login(self):
        repo = UserRepository(db_path=TEST_HOME / "auth7.db")
        user = repo.create(email="login@example.com")
        # Initially no last_login_at.
        assert user.last_login_at is None
        repo.touch_last_login(user.id)
        user2 = repo.get_by_id(user.id)
        assert user2.last_login_at is not None


class TestAutoFirstAdmin:
    def test_creates_admin(self):
        db = TEST_HOME / "auto1.db"
        user = auto_first_admin(
            email="auto@example.com",
            db_path=db,
        )
        assert user.is_first_admin is True
        assert user.email == "auto@example.com"
        assert user.username is not None

    def test_idempotent(self):
        db = TEST_HOME / "auto2.db"
        u1 = auto_first_admin(email="idemp@example.com", db_path=db)
        u2 = auto_first_admin(email="idemp@example.com", db_path=db)
        assert u1.id == u2.id


# ─── ApiKeyRepository ────────────────────────────────────────────


class TestApiKeyRepository:
    def test_schema_creation(self):
        db = TEST_HOME / "apikey1.db"
        ak_repo = ApiKeyRepository(db_path=db)
        assert db.exists()
        # api_keys table should exist.
        for row in ak_repo._connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'"
        ):
            assert row[0] == "api_keys"

    def test_create_and_get(self):
        db = TEST_HOME / "apikey2.db"
        # First create a user for FK.
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="pat_user@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        plain, pat_hash = generate_pat()
        ak = ak_repo.create(
            user_id=user.id,
            key_prefix=plain[:12],
            key_hash=pat_hash,
            name="test-key",
            scopes="write",
        )
        assert ak.key_prefix == plain[:12]
        assert ak.name == "test-key"
        fetched = ak_repo.get_by_id(ak.id)
        assert fetched is not None
        assert fetched.key_hash == pat_hash

    def test_get_by_hash(self):
        db = TEST_HOME / "apikey3.db"
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="hash_test@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        plain, pat_hash = generate_pat()
        ak_repo.create(
            user_id=user.id,
            key_prefix=plain[:12],
            key_hash=pat_hash,
            name="hash-test",
        )
        found = ak_repo.get_by_hash(pat_hash)
        assert found is not None
        assert found.user_id == user.id

    def test_list_by_user(self):
        db = TEST_HOME / "apikey4.db"
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="list_test@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        _, h1 = generate_pat()
        _, h2 = generate_pat()
        ak_repo.create(user_id=user.id, key_prefix="llmw_aaa", key_hash=h1, name="k1")
        ak_repo.create(user_id=user.id, key_prefix="llmw_bbb", key_hash=h2, name="k2")
        keys = ak_repo.list_by_user(user.id)
        assert len(keys) == 2

    def test_revoke(self):
        db = TEST_HOME / "apikey5.db"
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="revoke_test@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        _, pat_hash = generate_pat()
        ak = ak_repo.create(
            user_id=user.id,
            key_prefix="llmw_xxx",
            key_hash=pat_hash,
            name="to-revoke",
        )
        assert ak_repo.revoke(ak.id) is True
        # After revoke, get_by_hash should return None.
        assert ak_repo.get_by_hash(pat_hash) is None

    def test_revoke_already_revoked(self):
        db = TEST_HOME / "apikey6.db"
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="already_revoked@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        _, pat_hash = generate_pat()
        ak = ak_repo.create(
            user_id=user.id,
            key_prefix="llmw_yyy",
            key_hash=pat_hash,
            name="double-revoke",
        )
        assert ak_repo.revoke(ak.id) is True
        assert ak_repo.revoke(ak.id) is False

    def test_touch_last_used(self):
        db = TEST_HOME / "apikey7.db"
        u_repo = UserRepository(db_path=db)
        user = u_repo.create(email="touch_test@example.com")
        ak_repo = ApiKeyRepository(db_path=db)
        _, pat_hash = generate_pat()
        ak = ak_repo.create(
            user_id=user.id,
            key_prefix="llmw_zzz",
            key_hash=pat_hash,
            name="touch-test",
        )
        assert ak.last_used_at is None
        ak_repo.touch_last_used(ak.id)
        updated = ak_repo.get_by_id(ak.id)
        assert updated.last_used_at is not None
