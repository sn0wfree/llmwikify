"""Tests for interfaces.cli.commands.auth (Phase 2.5 — PAT-only auth).

Decisions exercised:
  - 9  chmod 600 on local_token
  - 11 auth.db location via LLMWIKIFY_HOME
  - 25 PAT replaces passwords (no password prompt)
  - 26 PAT format = llmw_ prefix + 24-byte hex
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Force a temp home BEFORE importing auth so module-level defaults
# don't cache the real path.
os.environ.setdefault(
    "LLMWIKIFY_HOME", tempfile.mkdtemp(prefix="llmwikify_cli_auth_test_")
)

# Stub keyring (CI envs may not have a daemon).
import keyring

_KEYRING_STORE: dict[tuple[str, str], str] = {}
keyring.set_password = lambda s, u, v: _KEYRING_STORE.__setitem__((s, u), v)  # type: ignore[assignment]
keyring.get_password = lambda s, u: _KEYRING_STORE.get((s, u))  # type: ignore[assignment]
keyring.delete_password = lambda s, u: _KEYRING_STORE.pop((s, u), None)  # type: ignore[assignment]


from llmwikify.foundation.auth import (  # noqa: E402
    ApiKeyRepository,
    UserRepository,
    generate_pat,
    hash_pat,
)
from llmwikify.interfaces.cli.commands.auth import (  # noqa: E402
    run_auth_create_token,
    run_auth_init,
    run_auth_list_tokens,
    run_auth_logout,
    run_auth_revoke_token,
    run_auth_token,
    run_auth_whoami,
)


class FakeTTY:
    """Stub stdin/stdout that looks like a TTY and returns queued lines."""

    def __init__(self, *lines: str) -> None:
        self._lines = list(lines)
        self._writes: list[str] = []

    def isatty(self) -> bool:
        return True

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0) + "\n"
        return ""

    def write(self, s: str) -> None:
        self._writes.append(s)

    def flush(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fresh_home(monkeypatch, tmp_path):
    """Each test gets its own LLMWIKIFY_HOME so the auth.db is fresh."""
    monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
    _KEYRING_STORE.clear()
    yield


# ─── auth init (interactive) ────────────────────────────────────


class TestAuthInitInteractive:
    def test_init_creates_user_and_local_token(self, monkeypatch):
        # PAT-only: only email prompt, no password.
        fake_stdin = FakeTTY("alice@example.com")
        fake_stdout = FakeTTY()
        with patch("sys.stdin", fake_stdin), patch("sys.stdout", fake_stdout):
            # run_auth_init signature: (wiki, config, args)
            # Build a minimal args namespace.
            import argparse
            args = argparse.Namespace(email=None)
            rc = run_auth_init(wiki=None, config={}, args=args)
        assert rc == 0

        # Verify local_token was written with chmod 600.
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        assert token_path.exists()
        mode = token_path.stat().st_mode & 0o777
        assert mode == 0o600, f"local_token mode {oct(mode)} != 0o600"

        # Verify user was created.
        repo = UserRepository()
        assert repo.exists()
        u = repo.get_by_email("alice@example.com")
        assert u is not None
        assert u.is_first_admin is True

        # Verify the printed token matches the file (minus newline).
        printed = "".join(fake_stdout._writes)
        assert "Your access token" in printed
        # Token is JWT-shaped (3 dot-separated base64 parts).
        token = token_path.read_text(encoding="utf-8").strip()
        assert token.count(".") == 2

    def test_init_no_tty_returns_1(self, monkeypatch):
        fake = io.StringIO()  # NOT a TTY
        with patch("sys.stdin", fake), patch("sys.stdout", fake):
            import argparse
            args = argparse.Namespace(email=None)
            rc = run_auth_init(wiki=None, config={}, args=args)
        assert rc == 1

    def test_init_with_email_non_interactive(self):
        import argparse
        args = argparse.Namespace(email="bob@example.com")
        rc = run_auth_init(wiki=None, config={}, args=args)
        assert rc == 0
        # local_token should exist.
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        assert token_path.exists()
        # User should exist.
        repo = UserRepository()
        assert repo.get_by_email("bob@example.com") is not None

    def test_init_non_interactive_without_email_returns_1(self):
        import argparse
        args = argparse.Namespace(email="")
        rc = run_auth_init(wiki=None, config={}, args=args)
        assert rc == 1

    def test_init_idempotent_same_email(self):
        # Run init twice with same email → second is a no-op (no error).
        import argparse
        args1 = argparse.Namespace(email="dup@e.com")
        rc1 = run_auth_init(wiki=None, config={}, args=args1)
        assert rc1 == 0
        args2 = argparse.Namespace(email="dup@e.com")
        rc2 = run_auth_init(wiki=None, config={}, args=args2)
        assert rc2 == 0
        # Only one user in the table.
        repo = UserRepository()
        assert repo.count() == 1


# ─── auth create-token ──────────────────────────────────────────


class TestAuthCreateToken:
    def test_create_token_creates_pat_and_local_token(self):
        import argparse
        # First init to create a user.
        init_args = argparse.Namespace(email="ct@e.com")
        run_auth_init(wiki=None, config={}, args=init_args)
        # Create a named token.
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_create_token(
                wiki=None, config={}, args=argparse.Namespace(name="laptop")
            )
        assert rc == 0
        printed = out.getvalue()
        assert "PAT created" in printed
        assert "llmw_" in printed
        # local_token should exist.
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        assert token_path.exists()

    def test_create_token_no_users_returns_1(self):
        import argparse
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_create_token(
                wiki=None, config={}, args=argparse.Namespace(name="test")
            )
        assert rc == 1
        assert "No users found" in err.getvalue()


# ─── auth list-tokens ───────────────────────────────────────────


class TestAuthListTokens:
    def test_list_tokens_after_init(self):
        import argparse
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email="lt@e.com"))
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_list_tokens(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
        printed = out.getvalue()
        # No tokens created yet besides implicit ones.
        assert "No PATs found" in printed or "ID" in printed

    def test_list_tokens_with_tokens(self):
        import argparse
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email="lt2@e.com"))
        # Create a token.
        err = io.StringIO()
        with patch("sys.stderr", err):
            run_auth_create_token(
                wiki=None, config={}, args=argparse.Namespace(name="mykey")
            )
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_list_tokens(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
        assert "mykey" in out.getvalue()

    def test_list_tokens_no_users_returns_1(self):
        import argparse
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_list_tokens(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 1
        assert "No users found" in err.getvalue()


# ─── auth revoke-token ──────────────────────────────────────────


class TestAuthRevokeToken:
    def test_revoke_existing_token(self):
        import argparse
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email="rt@e.com"))
        # Create a token so we have a key_id.
        create_out = io.StringIO()
        create_err = io.StringIO()
        with patch("sys.stdout", create_out), patch("sys.stderr", create_err):
            run_auth_create_token(
                wiki=None, config={}, args=argparse.Namespace(name="revoke-me")
            )
        # Get the key_id from ApiKeyRepository.
        repo = UserRepository()
        user = repo.get_by_email("rt@e.com")
        ak_repo = ApiKeyRepository()
        keys = ak_repo.list_by_user(user.id)
        assert len(keys) >= 1
        key_id = keys[0].id
        # Revoke it.
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_revoke_token(
                wiki=None, config={}, args=argparse.Namespace(key_id=key_id)
            )
        assert rc == 0
        assert "Revoked" in out.getvalue()

    def test_revoke_nonexistent_returns_1(self):
        import argparse
        # Init first so we have a user.
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email="rn@e.com"))
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_revoke_token(
                wiki=None, config={}, args=argparse.Namespace(key_id="nonexistent")
            )
        assert rc == 1
        assert "not found" in err.getvalue()

    def test_revoke_no_key_id_returns_1(self):
        import argparse
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_revoke_token(
                wiki=None, config={}, args=argparse.Namespace(key_id=None)
            )
        assert rc == 1


# ─── auth token ────────────────────────────────────────────────


class TestAuthToken:
    def test_token_after_init_writes_local_token(self):
        import argparse
        # First init.
        init_args = argparse.Namespace(email="d@e.com")
        run_auth_init(wiki=None, config={}, args=init_args)
        # Re-issue token.
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_token(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
        # The token is printed.
        printed = out.getvalue().strip()
        assert printed.count(".") == 2

    def test_token_with_no_users_returns_1(self):
        import argparse
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_token(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 1
        assert "No users found" in err.getvalue()


# ─── auth whoami ────────────────────────────────────────────────


class TestAuthWhoami:
    def test_whoami_no_token_returns_1(self):
        import argparse
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            rc = run_auth_whoami(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 1
        assert "No local_token" in err.getvalue()

    def test_whoami_prints_friendly_json(self):
        import argparse
        # Init then whoami.
        run_auth_init(
            wiki=None,
            config={},
            args=argparse.Namespace(email="e@e.com"),
        )
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_whoami(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
        body = json.loads(out.getvalue())
        assert body["email"] == "e@e.com"
        assert body["can_edit"] is True
        # Decision 1: no raw scope/sub in the friendly shape.
        assert "scope" not in body
        assert "sub" not in body
        # expires_at (unix timestamp) is the only time-related field.
        assert "expires_at" in body


# ─── auth logout ───────────────────────────────────────────────


class TestAuthLogout:
    def test_logout_removes_local_token(self):
        import argparse
        # First init.
        run_auth_init(
            wiki=None,
            config={},
            args=argparse.Namespace(email="f@e.com"),
        )
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        assert token_path.exists()
        # Logout.
        rc = run_auth_logout(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
        assert not token_path.exists()

    def test_logout_no_token_is_noop(self):
        import argparse
        rc = run_auth_logout(wiki=None, config={}, args=argparse.Namespace())
        assert rc == 0
