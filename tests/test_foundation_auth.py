"""Tests for foundation.auth — L1 primitives.

Phase 2a decision 16: Argon2id (t=3, m=64MB, p=4).
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
    hash_password,
    is_local_default,
    needs_rehash,
    verify_password,
)
from llmwikify.foundation.auth.db import User, UserRepository  # noqa: E402

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


# ─── Argon2id hash/verify (decision 16) ──────────────────────────


class TestArgon2id:
    def test_hash_format(self):
        h = hash_password("hunter2")
        assert h.startswith("$argon2id$")
        assert "v=19" in h
        assert "m=65536" in h
        assert "t=3" in h
        assert "p=4" in h

    def test_verify_correct(self):
        h = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("right")
        assert verify_password("wrong", h) is False

    def test_verify_corrupted_hash(self):
        assert verify_password("anything", "not-a-valid-hash") is False
        assert verify_password("anything", "$argon2id$v=19$garbage") is False

    def test_hash_unique_per_call(self):
        # Two hashes of the same password should differ (salt).
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_rehash_check(self):
        h = hash_password("password")
        # Just-generated hash should be at current params → no rehash needed.
        assert needs_rehash(h) is False

    def test_invalid_input_type(self):
        with pytest.raises(TypeError):
            hash_password(12345)  # type: ignore[arg-type]
        # verify_password should not raise, just return False.
        assert verify_password(12345, "ignored") is False  # type: ignore[arg-type]


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
            password="password123",
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
        repo.create(email="dup@example.com", password="password123")
        with pytest.raises(AuthError) as exc_info:
            repo.create(email="dup@example.com", password="password123")
        assert exc_info.value.code == "email_taken"

    def test_password_hash_is_argon2id(self):
        repo = UserRepository(db_path=TEST_HOME / "auth4.db")
        user = repo.create(email="bob@example.com", password="password123")
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password("password123", user.password_hash)

    def test_get_by_id_missing_returns_none(self):
        repo = UserRepository(db_path=TEST_HOME / "auth5.db")
        assert repo.get_by_id("nonexistent") is None

    def test_exists(self):
        repo = UserRepository(db_path=TEST_HOME / "auth6.db")
        assert repo.exists() is False
        repo.create(email="first@example.com", password="password123")
        assert repo.exists() is True

    def test_touch_last_login(self):
        repo = UserRepository(db_path=TEST_HOME / "auth7.db")
        user = repo.create(email="login@example.com", password="password123")
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
            password="password123",
            db_path=db,
        )
        assert user.is_first_admin is True
        assert user.email == "auto@example.com"
        assert user.username is not None

    def test_idempotent(self):
        db = TEST_HOME / "auto2.db"
        u1 = auto_first_admin(email="idemp@example.com", password="password123", db_path=db)
        u2 = auto_first_admin(email="idemp@example.com", password="password123", db_path=db)
        assert u1.id == u2.id
