"""Tests for interfaces.cli.commands.auth (Phase 2.5 — PAT-only auth).

Decisions exercised:
  - 9  chmod 600 on local_token
  - 11 auth.db location via LLMWIKIFY_HOME
  - 25 PAT replaces passwords (no password prompt)
  - 26 PAT format = llmw_ prefix + 24-byte hex
"""

from __future__ import annotations

import argparse
import io
import json
import os
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
)
from llmwikify.interfaces.cli.commands.auth import (  # noqa: E402
    run_auth_can_i,
    run_auth_create_token,
    run_auth_create_user,
    run_auth_disable_user,
    run_auth_enable_user,
    run_auth_grant,
    run_auth_init,
    run_auth_list_tokens,
    run_auth_list_users,
    run_auth_logout,
    run_auth_revoke_grant,
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

        # Verify local_token was written with chmod 600. Windows does not
        # model POSIX permission bits — stat().st_mode reports the default
        # ACL-backed mode — so the assertion only applies on POSIX.
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        assert token_path.exists()
        if os.name != "nt":
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

    def test_init_second_email_rejected_p1_1(self):
        """P1-1: a new email after an admin exists → registration_closed."""
        import argparse

        rc1 = run_auth_init(
            wiki=None, config={}, args=argparse.Namespace(email="a@e.com")
        )
        assert rc1 == 0

        err = io.StringIO()
        with patch("sys.stderr", err):
            rc2 = run_auth_init(
                wiki=None, config={}, args=argparse.Namespace(email="b@e.com")
            )
        assert rc2 == 1
        assert "admin already exists" in err.getvalue().lower()
        repo = UserRepository()
        assert repo.count() == 1
        assert repo.get_by_email("b@e.com") is None

    def test_init_pat_idempotent_p1_6(self):
        """P1-6: three same-email inits → exactly one cli-init PAT."""
        import argparse

        for _ in range(3):
            rc = run_auth_init(
                wiki=None, config={}, args=argparse.Namespace(email="p16@e.com")
            )
            assert rc == 0
        ak_repo = ApiKeyRepository()
        user = UserRepository().get_by_email("p16@e.com")
        keys = ak_repo.list_by_user(user.id)
        cli_init = [k for k in keys if k.name == "cli-init"]
        assert len(cli_init) == 1, f"expected 1 cli-init PAT, got {len(cli_init)}"

    def test_init_keeps_foreign_local_token_p1_3(self):
        """P1-3: init for another identity must not steal local_token."""
        import argparse

        rc = run_auth_init(
            wiki=None, config={}, args=argparse.Namespace(email="me@e.com")
        )
        assert rc == 0
        token_path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        mine = token_path.read_text(encoding="utf-8").strip()

        # Create a second user directly (CLI init would refuse — P1-1).
        other = UserRepository().create(email="colleague@e.com", is_first_admin=False)

        # Mint a PAT for the colleague; local_token must stay ours.
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_create_token(
                wiki=None,
                config={},
                args=argparse.Namespace(
                    name="for-colleague", user="colleague@e.com"
                ),
            )
        assert rc == 0
        assert token_path.read_text(encoding="utf-8").strip() == mine

        # PAT was issued to the colleague, not to us.
        keys = ApiKeyRepository().list_by_user(other.id)
        assert any(k.name == "for-colleague" for k in keys)

        # --force on init would replace it (same-email path writes ours back).
        rc = run_auth_init(
            wiki=None,
            config={},
            args=argparse.Namespace(email="me@e.com", force=True),
        )
        assert rc == 0


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

    def test_create_token_explicit_user_p1_2(self):
        """P1-2: --user selects the PAT owner by email / username / id."""
        import argparse

        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email="root@e.com"))
        # Second user via direct create (CLI init refuses — P1-1).
        other = UserRepository().create(
            email="bob@example.com", is_first_admin=False, username="bob"
        )

        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_create_token(
                wiki=None,
                config={},
                args=argparse.Namespace(name="bob-key", user="bob@example.com"),
            )
        assert rc == 0
        assert "bob@example.com" in out.getvalue()
        keys = ApiKeyRepository().list_by_user(other.id)
        assert any(k.name == "bob-key" for k in keys)

        # Username lookup works too.
        with patch("sys.stdout", io.StringIO()):
            rc = run_auth_create_token(
                wiki=None,
                config={},
                args=argparse.Namespace(name="bob-by-name", user="bob"),
            )
        assert rc == 0

        # Unknown target → exit 1, no PAT minted for anyone else.
        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_create_token(
                wiki=None,
                config={},
                args=argparse.Namespace(name="ghost", user="nobody@e.com"),
            )
        assert rc == 1
        assert "No user matching" in err.getvalue()


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


class TestSignLocalTokenGrant:
    """P1-4 + P3: grant-shaped tokens (admin keeps *, non-admin expands)."""

    def _claims(self, is_first_admin: bool, known_wikis: list[str] | None = None):
        from types import SimpleNamespace

        from llmwikify.foundation.auth import decode, set_secret
        from llmwikify.interfaces.cli.commands.auth import _sign_local_token

        user = SimpleNamespace(id="u-test", is_first_admin=is_first_admin)
        secret = set_secret()  # creates one on a fresh test home
        return decode(
            _sign_local_token(user, secret, known_wikis=known_wikis or []),
            secret,
        )

    def test_admin_keeps_write_scope(self):
        claims = self._claims(is_first_admin=True, known_wikis=["a", "b"])
        assert claims.scope == "write"
        assert claims.wikis == ["*"]
        assert claims.wgrants == {}

    def test_non_admin_no_grants_is_empty(self):
        """P3 + D8: zero grants → empty snapshot, read ceiling."""
        claims = self._claims(is_first_admin=False, known_wikis=["a", "b"])
        assert claims.scope == "read"
        assert claims.wikis == []
        assert claims.wgrants == {}

    def test_missing_flag_defaults_to_read(self):
        """A user record without the flag must not silently become admin."""
        from types import SimpleNamespace

        from llmwikify.foundation.auth import decode, set_secret
        from llmwikify.interfaces.cli.commands.auth import _sign_local_token

        user = SimpleNamespace(id="u-x")  # no is_first_admin attribute
        secret = set_secret()
        claims = decode(_sign_local_token(user, secret, known_wikis=[]), secret)
        assert claims.scope == "read"
        assert claims.wikis == []


class TestSnapshotForUserP3:
    """P3: snapshot_for_user — admin unchanged, non-admin expands grants."""

    @staticmethod
    def _snap(is_admin: bool, known: list[str], *, uid: str = "u-snap"):
        from llmwikify.foundation.auth import snapshot_for_user

        return snapshot_for_user(uid, known, is_admin=is_admin)

    def test_admin_unchanged(self):
        wikis, wgrants, scope = self._snap(True, ["a", "b", "c"])
        assert wikis == ["*"]
        assert wgrants == {}
        assert scope == "write"

    def test_non_admin_no_grants(self):
        wikis, wgrants, scope = self._snap(False, ["a", "b"])
        assert wikis == []
        assert wgrants == {}
        assert scope == "read"

    def test_non_admin_with_grants(self, monkeypatch, tmp_path):
        from llmwikify.foundation.auth import GrantRepository, snapshot_for_user

        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        repo = GrantRepository(db_path=tmp_path / "snap.db")
        repo.grant("user", "u-snap", "wiki-a", write=True)
        repo.grant("user", "u-snap", "wiki-b", read=True)

        wikis, wgrants, scope = snapshot_for_user(
            "u-snap", ["wiki-a", "wiki-b", "wiki-c"], is_admin=False,
            db_path=tmp_path / "snap.db",
        )
        assert set(wikis) == {"wiki-a", "wiki-b"}
        assert wgrants == {"wiki-a": "rw", "wiki-b": "r"}
        assert scope == "write"  # has at least one rw

    def test_non_admin_read_only_scope(self, monkeypatch, tmp_path):
        from llmwikify.foundation.auth import GrantRepository, snapshot_for_user

        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        repo = GrantRepository(db_path=tmp_path / "snap2.db")
        repo.grant("user", "u-snap", "wiki-a", read=True)

        wikis, wgrants, scope = snapshot_for_user(
            "u-snap", ["wiki-a"], is_admin=False, db_path=tmp_path / "snap2.db"
        )
        assert wikis == ["wiki-a"]
        assert wgrants == {"wiki-a": "r"}
        assert scope == "read"

    def test_wildcard_expands_in_snapshot(self, monkeypatch, tmp_path):
        from llmwikify.foundation.auth import (
            GrantRepository,
            snapshot_for_user,
        )

        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        repo = GrantRepository(db_path=tmp_path / "snap3.db")
        repo.grant("user", "u-snap", "*", read=True)

        wikis, wgrants, scope = snapshot_for_user(
            "u-snap", ["x", "y"], is_admin=False, db_path=tmp_path / "snap3.db"
        )
        assert set(wikis) == {"x", "y"}
        assert "*" not in wikis  # Q3-b: snapshot never contains the literal
        assert all(v == "r" for v in wgrants.values())
        assert scope == "read"


class TestGrantCLIP3:
    """P3: auth grant / revoke / can-i (admin-only)."""

    @staticmethod
    def _init_admin(email: str = "root@e.com") -> None:
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email=email))

    def test_grant_then_can_i(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="carol@e.com", is_first_admin=False)

        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_grant(
                None,
                {},
                argparse.Namespace(user="carol@e.com", wiki="wiki-a", write=False),
            )
        assert rc == 0
        assert "Granted" in out.getvalue()

        out2 = io.StringIO()
        with patch("sys.stdout", out2):
            rc2 = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="carol@e.com", wiki="wiki-a", write=False),
            )
        assert rc2 == 0
        assert out2.getvalue().strip() == "yes"

        # Not granted elsewhere.
        out3 = io.StringIO()
        with patch("sys.stdout", out3):
            rc3 = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="carol@e.com", wiki="wiki-b", write=False),
            )
        assert rc3 == 1
        assert out3.getvalue().strip() == "no"

    def test_grant_write_then_can_i_write(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="dave@e.com", is_first_admin=False)
        with patch("sys.stdout", io.StringIO()):
            run_auth_grant(
                None,
                {},
                argparse.Namespace(user="dave@e.com", wiki="wiki-a", write=True),
            )
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="dave@e.com", wiki="wiki-a", write=True),
            )
        assert rc == 0
        assert out.getvalue().strip() == "yes"

    def test_revoke_takes_effect(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="eve@e.com", is_first_admin=False)
        with patch("sys.stdout", io.StringIO()):
            run_auth_grant(
                None,
                {},
                argparse.Namespace(user="eve@e.com", wiki="wiki-a", write=True),
            )
        with patch("sys.stdout", io.StringIO()):
            rc = run_auth_revoke_grant(
                None, {}, argparse.Namespace(user="eve@e.com", wiki="wiki-a")
            )
        assert rc == 0
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc2 = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="eve@e.com", wiki="wiki-a", write=False),
            )
        assert rc2 == 1
        assert out.getvalue().strip() == "no"

    def test_wildcard_grant_covers_new_wiki(self):
        """Q3-c: a '*' grant covers a wiki created after the grant."""
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="fred@e.com", is_first_admin=False)
        with patch("sys.stdout", io.StringIO()):
            run_auth_grant(
                None,
                {},
                argparse.Namespace(user="fred@e.com", wiki="*", write=False),
            )
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="fred@e.com", wiki="brand-new", write=False),
            )
        assert rc == 0
        assert out.getvalue().strip() == "yes"

    def test_grant_requires_admin(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        other = UserRepository().create(email="bob@e.com", is_first_admin=False)
        # Switch identity to the non-admin.
        from llmwikify.foundation.auth import get_secret, require_secret
        from llmwikify.interfaces.cli.commands.auth import (
            _chmod_600,
            _local_token_path,
            _sign_local_token,
            ensure_dir_700,
        )

        secret = get_secret() or require_secret()
        token = _sign_local_token(other, secret, known_wikis=[])
        path = _local_token_path()
        ensure_dir_700(path.parent)
        path.write_text(token + "\n", encoding="utf-8", newline="\n")
        _chmod_600(path)

        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_grant(
                None,
                {},
                argparse.Namespace(user="bob@e.com", wiki="wiki-a", write=False),
            )
        assert rc == 1
        assert "Admin privileges required" in err.getvalue()

    def test_can_i_admin_always_yes(self):
        self._init_admin()
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_can_i(
                None,
                {},
                argparse.Namespace(user="root@e.com", wiki="anything", write=True),
            )
        assert rc == 0
        assert "yes" in out.getvalue()


class TestUserLifecycleCLIP2:
    """P2: create-user / list-users / disable-user / enable-user (admin-only)."""

    @staticmethod
    def _init_admin(email: str = "root@e.com") -> None:
        run_auth_init(wiki=None, config={}, args=argparse.Namespace(email=email))

    @staticmethod
    def _become(user) -> None:
        """Rewrite local_token to the given user's JWT (test helper)."""
        from llmwikify.foundation.auth import get_secret, require_secret
        from llmwikify.interfaces.cli.commands.auth import (
            _chmod_600,
            _local_token_path,
            _sign_local_token,
            ensure_dir_700,
        )

        secret = get_secret() or require_secret()
        token = _sign_local_token(user, secret)
        path = _local_token_path()
        ensure_dir_700(path.parent)
        path.write_text(token + "\n", encoding="utf-8", newline="\n")
        _chmod_600(path)

    def test_create_user_requires_admin(self):
        """Non-admin local_token → refuse (Q4)."""
        self._init_admin()
        # Create a non-admin and switch identity to them.
        from llmwikify.foundation.auth import UserRepository

        other = UserRepository().create(
            email="bob@e.com", is_first_admin=False
        )
        self._become(other)

        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_create_user(
                None, {}, argparse.Namespace(email="x@e.com")
            )
        assert rc == 1
        assert "Admin privileges required" in err.getvalue()
        assert UserRepository().get_by_email("x@e.com") is None

    def test_create_user_without_token_refuses(self):
        """No local_token → refuse (fail-closed)."""
        self._init_admin()
        path = Path(os.environ["LLMWIKIFY_HOME"]) / ".llmwikify" / "local_token"
        path.unlink(missing_ok=True)
        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_create_user(
                None, {}, argparse.Namespace(email="x@e.com")
            )
        assert rc == 1
        assert "local_token" in err.getvalue()

    def test_create_user(self):
        self._init_admin()
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_create_user(
                None, {}, argparse.Namespace(email="carol@e.com")
            )
        assert rc == 0
        assert "Created user" in out.getvalue()
        from llmwikify.foundation.auth import UserRepository

        u = UserRepository().get_by_email("carol@e.com")
        assert u is not None
        assert u.is_first_admin is False
        assert u.username == "carol"

    def test_create_user_duplicate_email(self):
        self._init_admin()
        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_create_user(
                None, {}, argparse.Namespace(email="root@e.com")
            )
        assert rc == 1
        assert "already exists" in err.getvalue()

    def test_list_users(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="dave@e.com", is_first_admin=False)
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_list_users(None, {}, argparse.Namespace())
        assert rc == 0
        text = out.getvalue()
        assert "root@e.com" in text
        assert "dave@e.com" in text
        assert "admin" in text
        assert "active" in text

    def test_disable_and_enable_user(self):
        self._init_admin()
        from llmwikify.foundation.auth import UserRepository

        UserRepository().create(email="eve@e.com", is_first_admin=False)

        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = run_auth_disable_user(
                None, {}, argparse.Namespace(user="eve@e.com")
            )
        assert rc == 0
        assert "Disabled" in out.getvalue()
        u = UserRepository().get_by_email("eve@e.com")
        assert u is not None and u.disabled_at is not None

        out2 = io.StringIO()
        with patch("sys.stdout", out2):
            rc2 = run_auth_enable_user(
                None, {}, argparse.Namespace(user="eve@e.com")
            )
        assert rc2 == 0
        assert "Enabled" in out2.getvalue()
        u2 = UserRepository().get_by_email("eve@e.com")
        assert u2 is not None and u2.disabled_at is None

    def test_disable_admin_refused(self):
        """Never allow disabling the admin (would lock the operator out)."""
        self._init_admin()
        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_disable_user(
                None, {}, argparse.Namespace(user="root@e.com")
            )
        assert rc == 1
        assert "admin" in err.getvalue().lower()
        from llmwikify.foundation.auth import UserRepository

        u = UserRepository().get_by_email("root@e.com")
        assert u is not None and u.disabled_at is None

    def test_disable_unknown_user(self):
        self._init_admin()
        err = io.StringIO()
        with patch("sys.stderr", err):
            rc = run_auth_disable_user(
                None, {}, argparse.Namespace(user="nobody@e.com")
            )
        assert rc == 1
        assert "No user matching" in err.getvalue()
