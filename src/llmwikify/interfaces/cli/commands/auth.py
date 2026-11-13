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
import logging
import sys
from typing import Any

from llmwikify.foundation.auth import (
    ApiKeyRepository,
    chmod_600,
    ensure_dir_700,
    generate_pat,
    local_token_path,
)

from .._base import Command

logger = logging.getLogger(__name__)

_local_token_path = local_token_path
_chmod_600 = chmod_600


def _sign_local_token(user: Any, secret: bytes) -> str:
    """Sign a local JWT whose grant matches ``user``'s role.

    P1-4: every token-issuance site used to hardcode
    ``scope="write", wikis=["*"]``, so any local user who ran
    ``auth token`` walked away with owner-level write access to every
    wiki regardless of whether they were an admin. Admins keep the full
    grant; everyone else gets a **read-only** token.

    Read scope still covers every wiki: decision 1 makes reads open, and
    there is no per-user wiki-grant table to narrow it by. Closing that
    gap needs a grant model, not a token flag (see
    docs/llmwikify-auth-缺陷清单.md P1-4).
    """
    from llmwikify.foundation.auth import TokenClaims, encode

    is_admin = bool(getattr(user, "is_first_admin", False))
    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope="write" if is_admin else "read",
        wikis=["*"],
    )
    return encode(claims, secret)


# ─── free functions ────────────────────────────────────────────────


def _should_write_local_token(user_id: str, *, force: bool = False) -> bool:
    """P1-3: never steal the caller's login identity.

    Write ``local_token`` only when there is no usable token yet, the
    existing token already belongs to ``user_id``, or ``--force``.
    """
    if force:
        return True
    path = _local_token_path()
    if not path.exists():
        return True
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    if not existing or existing == "local-mode-no-auth":  # noqa: S105 — sentinel
        return True
    try:
        from llmwikify.foundation.auth import decode, require_secret

        claims = decode(existing, require_secret())
    except Exception:
        return True  # unreadable / foreign secret → safe to replace
    return claims.sub == f"user:{user_id}"


def _write_local_token(user_id: str, token: str, *, force: bool = False) -> bool:
    """Write ``local_token`` for ``user_id`` unless it belongs to someone else.

    Returns True if the file was written, False if kept as-is (P1-3).
    """
    if not _should_write_local_token(user_id, force=force):
        return False
    token_path = _local_token_path()
    ensure_dir_700(token_path.parent)
    token_path.write_text(token + "\n", encoding="utf-8", newline="\n")
    _chmod_600(token_path)
    return True


def _resolve_user_spec(repo: Any, spec: str) -> Any | None:
    """P1-2: look up a user by email, then username, then id."""
    user = repo.get_by_email(spec)
    if user is None:
        user = repo.get_by_username(spec)
    if user is None:
        user = repo.get_by_id(spec)
    return user


def _ensure_init_pat(user_id: str, *, name: str = "cli-init") -> str | None:
    """P1-6: create the init PAT only if no active one with this name exists.

    Returns the plaintext PAT when newly minted, or None when reusing.
    """
    from llmwikify.foundation.auth import ApiKeyRepository

    ak_repo = ApiKeyRepository()
    if ak_repo.find_active(user_id, name) is not None:
        return None
    pat, pat_hash = generate_pat()
    ak_repo.create(
        user_id=user_id,
        key_prefix=pat[:12],
        key_hash=pat_hash,
        name=name,
        scopes="write",
    )
    return pat


def run_auth_init(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth init --email <you@example.com>`` (interactive).

    Decision 14 + 15: uses prompt_first_admin from foundation.auth.
    Decision 25: PAT-only — no password prompt.
    P1-1: second email → registration_closed (via auto_first_admin).
    P1-3: does not overwrite a local_token owned by another user
          unless ``--force``.
    P1-6: PAT creation is idempotent (same user + name → reuse).
    """
    from llmwikify.foundation.auth import AuthError, prompt_first_admin

    force = bool(getattr(args, "force", False))
    email = getattr(args, "email", None)
    if not email:
        try:
            result = prompt_first_admin()
        except Exception as exc:
            print(
                f"\n[!] {type(exc).__name__}: {getattr(exc, 'detail', exc)}",
                file=sys.stderr,
            )
            return 1
        email = result.user_email
        token = result.token
        pat = result.pat or None  # "" means an active init PAT was reused (P1-6)
        user_id = result.user_id
    else:
        # Non-interactive: create user + issue PAT.
        from llmwikify.foundation.auth import (
            auto_first_admin,
            get_secret,
            set_secret,
        )

        secret = get_secret()
        if not secret:
            secret = set_secret()
        try:
            user = auto_first_admin(email=email)
        except AuthError as exc:
            print(f"[!] {exc.detail}", file=sys.stderr)
            return 1
        user_id = user.id

        # P1-6: reuse an active cli-init PAT instead of stacking copies.
        pat = _ensure_init_pat(user_id, name="cli-init")
        if pat is not None:
            from llmwikify.foundation.auth.utils import save_pat

            save_pat(pat)

        token = _sign_local_token(user, secret)

    # P1-3: only adopt/replace local_token when it is ours (or --force).
    wrote = _write_local_token(user_id, token, force=force)

    print("✓ JWT secret saved to OS keyring (llmwikify/jwt_secret)")
    print(f"✓ First admin ready: {email}")
    token_path = _local_token_path()
    if wrote:
        print(f"✓ local_token saved to {token_path} (chmod 600)")
    else:
        print(
            f"✓ local_token left unchanged (owned by another user); "
            f"use --force to replace {token_path}"
        )
    if pat:
        print()
        print("Your access token (30d, scope=write, wikis=*):")
        print(f"  {token}")
        print()
        print("WebUI: open http://127.0.0.1:8765 and paste your PAT")
        print('CLI:   export LLMWIKIFY_AUTH_TOKEN="<the-token-above>"')
    else:
        print()
        print("Existing PAT reused (not re-printed); manage via `auth list-tokens`.")
        print(f"local_token JWT:\n  {token}")
    return 0


def run_auth_create_token(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth create-token --name <label> [--user <id>]``

    Creates a new PAT, optionally for ``--user`` (P1-2: email / username /
    id; default = current local_token identity, else first user).
    Writes local_token only when it already belongs to that user or is
    absent (P1-3 — creating a token for a colleague must not steal yours).
    """
    from llmwikify.foundation.auth import (
        UserRepository,
        require_secret,
    )

    name = getattr(args, "name", None) or "cli"
    user_spec = getattr(args, "user", None)

    repo = UserRepository()
    user = None

    if user_spec:
        # P1-2: explicit target wins over local_token / LIMIT 1 fallback.
        user = _resolve_user_spec(repo, user_spec)
        if user is None:
            print(
                f"[!] No user matching {user_spec!r} "
                "(tried email, username, id).",
                file=sys.stderr,
            )
            return 1
    else:
        # Find the first user (or from existing local_token).
        try:
            existing = _local_token_path().read_text(encoding="utf-8").strip()
            if existing and existing != "local-mode-no-auth":
                from llmwikify.foundation.auth import decode

                try:
                    claims = decode(existing, require_secret())
                    if claims.sub.startswith("user:"):
                        user = repo.get_by_id(claims.sub[len("user:") :])
                except Exception:
                    logger.debug(
                        "Could not decode existing token for user lookup",
                        exc_info=True,
                    )
        except FileNotFoundError:
            logger.debug("No existing local_token file found")

    if user is None:
        # Fallback: first row (legacy behaviour when no local_token).
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

    # Sign a JWT for this user; P1-3: do not clobber someone else's token.
    token = _sign_local_token(user, require_secret())
    wrote = _write_local_token(user.id, token, force=False)

    print(f"✓ PAT created: {ak.key_prefix}... ({name}) for {user.email}")
    print()
    print("Your PAT (save it — shown once):")
    print(f"  {pat}")
    print()
    if wrote:
        print(f"✓ local_token updated: {_local_token_path()}")
    else:
        print(
            "✓ local_token left unchanged (belongs to another user); "
            "run `auth token` to switch identity."
        )
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
                user = repo.get_by_id(claims.sub[len("user:") :])
    except Exception:
        logger.debug("Could not decode existing token for list-tokens", exc_info=True)

    if user is None:
        print("[!] No users found. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1

    ak_repo = ApiKeyRepository()
    keys = ak_repo.list_by_user(user.id)

    if not keys:
        print("No PATs found.")
        return 0

    print(
        f"{'ID':<12} {'Prefix':<14} {'Name':<20} {'Created':<20} {'Last Used':<20} {'Status'}"
    )
    print("-" * 100)
    for k in keys:
        status = "active" if k.revoked_at is None else f"revoked {k.revoked_at}"
        if k.expires_at:
            status += f" (exp: {k.expires_at})"
        last_used = k.last_used_at or "never"
        print(
            f"{k.id[:12]}  {k.key_prefix:<14} {(k.name or '-'):<20} {k.created_at:<20} {last_used:<20} {status}"
        )
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
                user = repo.get_by_id(claims.sub[len("user:") :])
    except Exception:
        logger.debug("Could not decode existing token for revoke-token", exc_info=True)

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
        UserRepository,
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
                    user = repo.get_by_id(claims.sub[len("user:") :])
            except Exception:
                logger.debug(
                    "Could not decode existing token for auth token", exc_info=True
                )
    except FileNotFoundError:
        logger.debug("No existing local_token file found")

    if user is None:
        for row in repo._connect().execute("SELECT * FROM users LIMIT 1"):
            from llmwikify.foundation.auth.db import _row_to_user

            user = _row_to_user(row)
            break

    if user is None:
        print("[!] No users found. Run `llmwikify auth init` first.", file=sys.stderr)
        return 1

    token = _sign_local_token(user, require_secret())
    token_path = _local_token_path()
    ensure_dir_700(token_path.parent)
    token_path.write_text(token + "\n", encoding="utf-8", newline="\n")
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
    if (
        not token or token == "local-mode-no-auth"
    ):  # noqa: S105 — sentinel, not a password
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
        user = UserRepository().get_by_id(claims.sub[len("user:") :])
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
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite local_token even if it belongs to another user",
    )

    # create-token
    p_ct = auth_sub.add_parser("create-token", help="Create a new PAT")
    p_ct.add_argument("--name", help="Label for this token (e.g. 'laptop')")
    p_ct.add_argument(
        "--user",
        help="Target user (email / username / id; default: local_token identity)",
    )

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
            print(
                "Usage: llmwikify auth {init,create-token,list-tokens,revoke-token,token,whoami,logout}",
                file=sys.stderr,
            )
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
