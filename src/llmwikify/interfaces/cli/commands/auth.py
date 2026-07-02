"""``auth`` command — bootstrap and inspect the local auth state.

Subcommands (Phase 2a):
  init      Create the first admin + JWT signing secret
  token     Issue a fresh owner JWT and write to local_token
  whoami    Decode a JWT and show user identity
  logout    Clear local_token (revoke client-side; server-side
            invalidation requires Phase 3 share-token blocklist)

Decisions:
  - 7  wikis claim re-signed on every `token` call (picks up newly
        registered wikis)
  - 9  local_token written with chmod 600
  - 11 auth.db location: ~/.llmwikify/auth.db (single source of truth)
  - 15 TTY fallback: init prompts via prompt_first_admin; if not a
        TTY, print a clear hint + exit 1
  - 18 stdlib input() + getpass.getpass() (no questionary)
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .._base import Command


# Canonical paths (mirrored in foundation/auth/db.py; we re-import to
# avoid duplicating constants).
def _local_token_path() -> Path:
    home = os.environ.get("LLMWIKIFY_HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / ".llmwikify" / "local_token"


def _chmod_600(path: Path) -> None:
    """Set POSIX permissions 0o600 on a file. No-op on Windows."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best effort


# ─── free functions (runnable from main() dispatch) ────────────────


def run_auth_init(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth init --email <you@example.com>`` (interactive).

    Decision 14 + 15: we use the shared prompt_first_admin from
    foundation.auth so the same TTY fallback + stdlib prompts apply
    whether triggered by `auth init` or by `serve --host non-loopback`.
    """
    from llmwikify.foundation.auth import prompt_first_admin

    email = getattr(args, "email", None)
    if not email:
        # Defer to interactive prompt; we need a TTY.
        try:
            result = prompt_first_admin()
        except Exception as exc:  # AuthError, etc.
            print(f"\n[!] {type(exc).__name__}: {getattr(exc, 'detail', exc)}", file=sys.stderr)
            return 1
        email = result.user_email
        token = result.token
    else:
        # Non-interactive: require --password
        password = getattr(args, "password", None)
        if not password:
            print(
                "[!] Non-interactive mode requires --password <pw> "
                "(or omit --email to use interactive prompt).",
                file=sys.stderr,
            )
            return 1
        # Lazy imports so the CLI doesn't pay the auth.cost until used.
        # Ensure keyring has a secret.
        from llmwikify.foundation.auth import (
            TokenClaims,
            UserRepository,
            auto_first_admin,
            encode,
            get_secret,
            set_secret,
        )
        secret = get_secret()
        if not secret:
            secret = set_secret()
        user = auto_first_admin(email=email, password=password)
        claims = TokenClaims.new(
            sub=f"user:{user.id}",
            scope="write",
            wikis=["*"],
        )
        token = encode(claims, secret)

    # Write to local_token with chmod 600.
    token_path = _local_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(token_path.parent, 0o700)
    except OSError:
        pass
    token_path.write_text(token + "\n", encoding="utf-8")
    _chmod_600(token_path)

    print("✓ JWT secret saved to OS keyring (llmwikify/jwt_secret)")
    print(f"✓ First admin created: {email}")
    print(f"✓ local_token saved to {token_path} (chmod 600)")
    print()
    print("Your access token (30d, scope=write, wikis=*):")
    print(f"  {token}")
    print()
    print("WebUI: open http://127.0.0.1:8765 in your browser and use /auth/login")
    print("CLI:   export LLMWIKIFY_AUTH_TOKEN=\"<the-token-above>\"")
    return 0


def run_auth_token(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth token`` — re-sign a fresh JWT, write to local_token.

    Useful when:
      - the user added new wikis (wikis claim is updated)
      - the existing token is about to expire
      - the local_token file was lost
    """
    from llmwikify.foundation.auth import (
        TokenClaims,
        UserRepository,
        encode,
        require_secret,
    )

    repo = UserRepository()
    user = None
    # Try to recover the existing admin from local_token first.
    try:
        existing = _local_token_path().read_text(encoding="utf-8").strip()
        if existing and existing != "local-mode-no-auth":
            from llmwikify.foundation.auth import decode
            try:
                claims = decode(existing, require_secret())
                if claims.sub.startswith("user:"):
                    user = repo.get_by_id(claims.sub[len("user:"):])
            except Exception:
                pass
    except FileNotFoundError:
        pass
    if user is None:
        # Fall back to first user in the table.
        all_users = []
        for row in repo._connect().execute("SELECT * FROM users LIMIT 1"):
            all_users.append(row)
        if not all_users:
            print(
                "[!] No users found. Run `llmwikify auth init` first.",
                file=sys.stderr,
            )
            return 1
        from llmwikify.foundation.auth.db import _row_to_user
        user = _row_to_user(all_users[0])

    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write",
        wikis=["*"],  # owner is wildcard
    )
    token = encode(claims, require_secret())
    token_path = _local_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(token_path.parent, 0o700)
    except OSError:
        pass
    token_path.write_text(token + "\n", encoding="utf-8")
    _chmod_600(token_path)
    print(token)
    return 0


def run_auth_whoami(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth whoami`` — decode the local_token and show identity.

    Decision 1: shows the friendly shape (`email`, `can_edit`, `wikis`)
    not the raw scope string. If no token is found, exit 1 with hint.
    """
    from llmwikify.foundation.auth import (
        UserRepository,
        decode,
        require_secret,
    )

    try:
        token = _local_token_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(
            "[!] No local_token at ~/.llmwikify/local_token. "
            "Run `llmwikify auth init` or `llmwikify auth token` first.",
            file=sys.stderr,
        )
        return 1
    if not token or token == "local-mode-no-auth":
        print(
            "[!] local_token is the local-mode marker; no real auth. "
            "Re-init to get a real token.",
            file=sys.stderr,
        )
        return 1
    try:
        claims = decode(token, require_secret())
    except Exception as exc:
        print(f"[!] Token decode failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    user_email: str | None = None
    is_first_admin = False
    if claims.sub.startswith("user:"):
        user = UserRepository().get_by_id(claims.sub[len("user:"):])
        if user is not None:
            user_email = user.email
            is_first_admin = user.is_first_admin

    payload = {
        "sub": claims.sub,
        "email": user_email,
        "is_first_admin": is_first_admin,
        "can_edit": claims.scope == "write",
        "scope": claims.scope,
        "wikis": list(claims.wikis),
        "exp": claims.exp,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def run_auth_logout(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth logout`` — remove local_token.

    Phase 2a note: this only removes the local copy. The server cannot
    revoke the JWT itself (no refresh-token / blocklist yet). The token
    remains valid for up to 30 days until exp. Phase 3 will add a
    share_token blocklist; Phase 4 may add a real logout endpoint.
    """
    path = _local_token_path()
    if path.exists():
        path.unlink()
        print(f"✓ Removed {path}")
    else:
        print(f"No local_token at {path}; nothing to do.")
    return 0


# ─── argparse subparser ────────────────────────────────────────────


def setup_auth_parser(subparsers: Any) -> None:
    """Add the ``auth`` subparser with init/token/whoami/logout."""
    from argparse import _SubParsersAction

    if not isinstance(subparsers, _SubParsersAction):
        raise TypeError("setup_parser requires an argparse subparsers action")

    p = subparsers.add_parser("auth", help="Auth bootstrap + inspection")
    auth_sub = p.add_subparsers(
        dest="auth_command",
        help="Auth subcommand",
    )

    # init
    p_init = auth_sub.add_parser("init", help="Create the first admin user")
    p_init.add_argument("--email", help="Email (omit for interactive prompt)")
    p_init.add_argument("--password", help="Password (omit for interactive prompt)")

    # token
    auth_sub.add_parser(
        "token", help="Re-sign a fresh owner JWT and write to local_token",
    )

    # whoami
    auth_sub.add_parser("whoami", help="Show current user identity from local_token")

    # logout
    auth_sub.add_parser("logout", help="Remove local_token")


# ─── Command class (registry entry) ──────────────────────────────


class AuthCommand(Command):
    """``auth`` command — bootstrap and inspect the local auth state."""

    name = "auth"
    help = "Auth bootstrap + inspection"

    def setup_parser(self, subparsers: Any) -> None:
        setup_auth_parser(subparsers)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        sub = getattr(args, "auth_command", None)
        if sub is None:
            print("Usage: llmwikify auth {init,token,whoami,logout}", file=sys.stderr)
            return 1
        if sub == "init":
            return run_auth_init(wiki, config, args)
        if sub == "token":
            return run_auth_token(wiki, config, args)
        if sub == "whoami":
            return run_auth_whoami(wiki, config, args)
        if sub == "logout":
            return run_auth_logout(wiki, config, args)
        print(f"Unknown auth subcommand: {sub}", file=sys.stderr)
        return 1
