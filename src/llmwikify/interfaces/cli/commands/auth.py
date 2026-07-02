"""``auth`` command — bootstrap and inspect the local auth state.

Subcommands (Phase 2.5, PAT-only auth):
  init          Create the first admin user (email only, no password)
  create-token  Create a new PAT and save to local_token
  list-tokens   List all PATs for the current user
  revoke-token  Revoke a PAT by ID
  token         Re-sign a fresh owner JWT and write to local_token
  whoami        Decode a JWT and show user identity
  logout        Clear local_token (client-side only)

Decisions:
  - 7  wikis claim re-signed on every `token` call
  - 9  local_token written with chmod 600
  - 11 auth.db location: ~/.llmwikify/auth.db
  - 15 TTY fallback: init prompts via prompt_first_admin
  - 25 PAT replaces passwords (no password prompt)
  - 26 PAT format = llmw_ prefix + 24-byte hex
"""

from __future__ import annotations

import json
import sys
from typing import Any

from llmwikify.foundation.auth import (
    ApiKeyRepository,
    chmod_600,
    ensure_dir_700,
    generate_pat,
    hash_pat,
    local_token_path,
)

from .._base import Command

_local_token_path = local_token_path
_chmod_600 = chmod_600


# ─── free functions ────────────────────────────────────────────────


def run_auth_init(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth init --email <you@example.com>`` (interactive).

    Decision 14 + 15: uses prompt_first_admin from foundation.auth.
    Decision 25: PAT-only — no password prompt.
    """
    from llmwikify.foundation.auth import prompt_first_admin

    email = getattr(args, "email", None)
    if not email:
        try:
            result = prompt_first_admin()
        except Exception as exc:
            print(f"\n[!] {type(exc).__name__}: {getattr(exc, 'detail', exc)}", file=sys.stderr)
            return 1
        email = result.user_email
        token = result.token
    else:
        # Non-interactive: create user + issue PAT.
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
        user = auto_first_admin(email=email)

        # Generate PAT + save.
        pat, pat_hash = generate_pat()
        ak_repo = ApiKeyRepository()
        ak_repo.create(
            user_id=user.id,
            key_prefix=pat[:12],
            key_hash=pat_hash,
            name="cli-init",
            scopes="write",
        )
        from llmwikify.foundation.auth.utils import save_pat
        save_pat(pat)

        claims = TokenClaims.new(
            sub=f"user:{user.id}",
            scope="write",
            wikis=["*"],
        )
        token = encode(claims, secret)

    # Write to local_token with chmod 600.
    token_path = _local_token_path()
    ensure_dir_700(token_path.parent)
    token_path.write_text(token + "\n", encoding="utf-8")
    _chmod_600(token_path)

    print("✓ JWT secret saved to OS keyring (llmwikify/jwt_secret)")
    print(f"✓ First admin created: {email}")
    print(f"✓ local_token saved to {token_path} (chmod 600)")
    print()
    print("Your access token (30d, scope=write, wikis=*):")
    print(f"  {token}")
    print()
    print("WebUI: open http://127.0.0.1:8765 and paste your PAT")
    print("CLI:   export LLMWIKIFY_AUTH_TOKEN=\"<the-token-above>\"")
    return 0


def run_auth_create_token(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth create-token --name <label>``

    Creates a new PAT, saves to local_token, prints once.
    """
    from llmwikify.foundation.auth import (
        TokenClaims,
        UserRepository,
        encode,
        require_secret,
    )

    name = getattr(args, "name", None) or "cli"

    # Find the first user (or from existing local_token).
    repo = UserRepository()
    user = None
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
        for row in repo._connect().execute("SELECT * FROM users LIMIT 1"):
            from llmwikify.foundation.auth.db import _row_to_user
            user = _row_to_user(row)
            break

    if user is None:
        print("[!] No users found. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1

    # Generate PAT.
    pat, pat_hash = generate_pat()
    ak_repo = ApiKeyRepository()
    ak = ak_repo.create(
        user_id=user.id,
        key_prefix=pat[:12],
        key_hash=pat_hash,
        name=name,
        scopes="write",
    )

    # Also sign a JWT and save to local_token.
    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write",
        wikis=["*"],
    )
    token = encode(claims, require_secret())
    token_path = _local_token_path()
    ensure_dir_700(token_path.parent)
    token_path.write_text(token + "\n", encoding="utf-8")
    _chmod_600(token_path)

    print(f"✓ PAT created: {ak.key_prefix}... ({name})")
    print()
    print("Your PAT (save it — shown once):")
    print(f"  {pat}")
    print()
    print(f"✓ local_token updated: {token_path}")
    return 0


def run_auth_list_tokens(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth list-tokens`` — list all PATs."""
    from llmwikify.foundation.auth import (
        UserRepository,
        decode,
        require_secret,
    )

    repo = UserRepository()
    user = None
    try:
        existing = _local_token_path().read_text(encoding="utf-8").strip()
        if existing and existing != "local-mode-no-auth":
            claims = decode(existing, require_secret())
            if claims.sub.startswith("user:"):
                user = repo.get_by_id(claims.sub[len("user:"):])
    except Exception:
        pass

    if user is None:
        print("[!] No users found. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1

    ak_repo = ApiKeyRepository()
    keys = ak_repo.list_by_user(user.id)

    if not keys:
        print("No PATs found.")
        return 0

    print(f"{'ID':<12} {'Prefix':<14} {'Name':<20} {'Created':<20} {'Last Used':<20} {'Status'}")
    print("-" * 100)
    for k in keys:
        status = "active" if k.revoked_at is None else f"revoked {k.revoked_at}"
        if k.expires_at:
            status += f" (exp: {k.expires_at})"
        last_used = k.last_used_at or "never"
        print(f"{k.id[:12]}  {k.key_prefix:<14} {(k.name or '-'):<20} {k.created_at:<20} {last_used:<20} {status}")
    return 0


def run_auth_revoke_token(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth revoke-token <id>`` — revoke a PAT."""
    from llmwikify.foundation.auth import (
        UserRepository,
        decode,
        require_secret,
    )

    key_id = getattr(args, "key_id", None)
    if not key_id:
        print("[!] Usage: llmwikify auth revoke-token <key-id>", file=sys.stderr)
        return 1

    repo = UserRepository()
    user = None
    try:
        existing = _local_token_path().read_text(encoding="utf-8").strip()
        if existing and existing != "local-mode-no-auth":
            claims = decode(existing, require_secret())
            if claims.sub.startswith("user:"):
                user = repo.get_by_id(claims.sub[len("user:"):])
    except Exception:
        pass

    if user is None:
        print("[!] No users found.", file=sys.stderr)
        return 1

    ak_repo = ApiKeyRepository()
    ak = ak_repo.get_by_id(key_id)
    if ak is None or ak.user_id != user.id:
        print(f"[!] API key {key_id!r} not found.", file=sys.stderr)
        return 1

    if ak_repo.revoke(key_id):
        print(f"✓ Revoked PAT: {ak.key_prefix}... ({ak.name or 'unnamed'})")
    else:
        print(f"PAT {key_id} was already revoked.")
    return 0


def run_auth_token(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth token`` — re-sign a fresh JWT, write to local_token."""
    from llmwikify.foundation.auth import (
        TokenClaims,
        UserRepository,
        encode,
        require_secret,
    )

    repo = UserRepository()
    user = None
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
        for row in repo._connect().execute("SELECT * FROM users LIMIT 1"):
            from llmwikify.foundation.auth.db import _row_to_user
            user = _row_to_user(row)
            break

    if user is None:
        print("[!] No users found. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1

    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write",
        wikis=["*"],
    )
    token = encode(claims, require_secret())
    token_path = _local_token_path()
    ensure_dir_700(token_path.parent)
    token_path.write_text(token + "\n", encoding="utf-8")
    _chmod_600(token_path)
    print(token)
    return 0


def run_auth_whoami(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth whoami`` — decode the local_token and show identity."""
    from llmwikify.foundation.auth import (
        UserRepository,
        decode,
        require_secret,
    )

    try:
        token = _local_token_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print("[!] No local_token. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1
    if not token or token == "local-mode-no-auth":
        print("[!] local_token is the local-mode marker.", file=sys.stderr)
        return 1
    try:
        claims = decode(token, require_secret())
    except Exception as exc:
        print(f"[!] Token decode failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    user_email = None
    is_first_admin = False
    if claims.sub.startswith("user:"):
        user = UserRepository().get_by_id(claims.sub[len("user:"):])
        if user is not None:
            user_email = user.email
            is_first_admin = user.is_first_admin

    payload = {
        "email": user_email,
        "is_first_admin": is_first_admin,
        "can_edit": claims.scope == "write",
        "wikis": list(claims.wikis),
        "expires_at": claims.exp,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def run_auth_logout(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth logout`` — remove local_token."""
    path = _local_token_path()
    if path.exists():
        path.unlink()
        print(f"✓ Removed {path}")
    else:
        print(f"No local_token at {path}; nothing to do.")
    return 0


# ─── argparse subparser ────────────────────────────────────────────


def setup_auth_parser(subparsers: Any) -> None:
    from argparse import _SubParsersAction

    if not isinstance(subparsers, _SubParsersAction):
        raise TypeError("setup_parser requires an argparse subparsers action")

    p = subparsers.add_parser("auth", help="Auth bootstrap + inspection")
    auth_sub = p.add_subparsers(dest="auth_command", help="Auth subcommand")

    # init
    p_init = auth_sub.add_parser("init", help="Create the first admin user")
    p_init.add_argument("--email", help="Email (omit for interactive prompt)")

    # create-token
    p_ct = auth_sub.add_parser("create-token", help="Create a new PAT")
    p_ct.add_argument("--name", help="Label for this token (e.g. 'laptop')")

    # list-tokens
    auth_sub.add_parser("list-tokens", help="List all PATs")

    # revoke-token
    p_rt = auth_sub.add_parser("revoke-token", help="Revoke a PAT by ID")
    p_rt.add_argument("key_id", nargs="?", help="API key ID to revoke")

    # token
    auth_sub.add_parser("token", help="Re-sign a fresh owner JWT")

    # whoami
    auth_sub.add_parser("whoami", help="Show current user identity")

    # logout
    auth_sub.add_parser("logout", help="Remove local_token")


# ─── Command class ──────────────────────────────────────────────


class AuthCommand(Command):
    """``auth`` command — bootstrap and inspect the local auth state."""

    name = "auth"
    help = "Auth bootstrap + inspection"

    def setup_parser(self, subparsers: Any) -> None:
        setup_auth_parser(subparsers)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        sub = getattr(args, "auth_command", None)
        if sub is None:
            print("Usage: llmwikify auth {init,create-token,list-tokens,revoke-token,token,whoami,logout}", file=sys.stderr)
            return 1
        if sub == "init":
            return run_auth_init(wiki, config, args)
        if sub == "create-token":
            return run_auth_create_token(wiki, config, args)
        if sub == "list-tokens":
            return run_auth_list_tokens(wiki, config, args)
        if sub == "revoke-token":
            return run_auth_revoke_token(wiki, config, args)
        if sub == "token":
            return run_auth_token(wiki, config, args)
        if sub == "whoami":
            return run_auth_whoami(wiki, config, args)
        if sub == "logout":
            return run_auth_logout(wiki, config, args)
        print(f"Unknown auth subcommand: {sub}", file=sys.stderr)
        return 1
