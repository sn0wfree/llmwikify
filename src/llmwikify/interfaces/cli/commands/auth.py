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


def _known_wiki_ids(config: dict | None = None) -> list[str]:
    """Enumerate registered wiki ids for token snapshots (P3).

    Interfaces may import kernel. Falls back to ``[]`` on any failure —
    an empty snapshot is safe (deny-by-default for non-admins).
    """
    try:
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        registry = WikiRegistry(config or {})
        registry.initialize()
        try:
            return [w.wiki_id for w in registry.list_wikis()]
        finally:
            registry.close()
    except Exception:
        logger.debug("wiki enumeration failed", exc_info=True)
        return []


def _sign_local_token(
    user: Any, secret: bytes, known_wikis: list[str] | None = None
) -> str:
    """Sign a local JWT whose grant matches ``user``'s role.

    P1-4: non-admins never get owner-level write by default.
    P3: the snapshot comes from ``snapshot_for_user`` —
      * admin  → ``wikis=["*"]``, ``wgrants={}``, ``scope=write`` (G5, unchanged)
      * non-admin → concrete expanded lists from ``wiki_grants`` (Q3-b);
        ``scope=write`` iff any per-wiki grant is ``rw`` (D4).

    ``known_wikis`` defaults to enumerating the registry; pass ``[]``
    only in tests that deliberately want an empty snapshot.
    """
    from llmwikify.foundation.auth import TokenClaims, encode, snapshot_for_user

    if known_wikis is None:
        known_wikis = _known_wiki_ids()
    wikis, wgrants, scope = snapshot_for_user(
        user.id,
        known_wikis,
        is_admin=bool(getattr(user, "is_first_admin", False)),
    )
    claims = TokenClaims.new(
        sub=f"user:{user.id}",
        scope=scope,
        wikis=wikis,
        wgrants=wgrants,
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
            user = repo.first_user()

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
        user = repo.first_user()

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


# ─── P2: user lifecycle helpers ────────────────────────────────


def _resolve_local_user() -> Any | None:
    """Resolve the identity behind ``local_token`` (or None)."""
    from llmwikify.foundation.auth import UserRepository, decode, require_secret

    try:
        existing = _local_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not existing or existing == "local-mode-no-auth":  # noqa: S105 — sentinel
        return None
    try:
        claims = decode(existing, require_secret())
    except Exception:
        logger.debug("local_token decode failed", exc_info=True)
        return None
    if not claims.sub.startswith("user:"):
        return None
    return UserRepository().get_by_id(claims.sub[len("user:") :])


def _require_admin() -> Any | None:
    """Return the current admin user, or print an error and return None.

    Q4: create-user / list-users / disable-user / enable-user are admin-only.
    Fail-closed: no token, unresolvable identity, or non-admin → refuse.
    """
    user = _resolve_local_user()
    if user is None:
        print(
            "[!] Cannot resolve identity from local_token. "
            "Run `llmwikify auth token` first.",
            file=sys.stderr,
        )
        return None
    if not user.is_first_admin:
        print(
            "[!] Admin privileges required for this command (Q4).",
            file=sys.stderr,
        )
        return None
    return user


def run_auth_create_user(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth create-user --email <you@example.com>`` (P2).

    Creates a **non-admin** user. Admins are locked to the first account
    (P1-1 ``registration_closed``; Q2 defers owner semantics).
    """
    from llmwikify.foundation.auth import AuthError, UserRepository

    if _require_admin() is None:
        return 1

    email = (getattr(args, "email", "") or "").strip()
    if not email or "@" not in email:
        print("[!] --email is required (a valid address).", file=sys.stderr)
        return 1

    repo = UserRepository()
    try:
        user = repo.create(email=email, is_first_admin=False)
    except AuthError as exc:
        print(f"[!] {exc.detail}", file=sys.stderr)
        return 1

    print(f"✓ Created user: {user.email} (username={user.username}, non-admin)")
    print("  Next: `llmwikify auth grant --user "
          f"{user.email} --wiki <wiki-id> --read` to grant access.")
    return 0


def run_auth_list_users(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth list-users`` — table of users + status (P2)."""
    from llmwikify.foundation.auth import UserRepository

    if _require_admin() is None:
        return 1

    users = UserRepository().list_users()
    if not users:
        print("No users found.")
        return 0

    print(f"{'ID':<12} {'Email':<28} {'Username':<20} {'Role':<8} {'Status':<10}")
    print("-" * 80)
    for u in users:
        role = "admin" if u.is_first_admin else "user"
        status = "disabled" if u.disabled_at else "active"
        print(f"{u.id[:12]:<12} {u.email:<28} {(u.username or '-'):<20} "
              f"{role:<8} {status:<10}")
    print()
    print(f"Total: {len(users)} user(s)")
    return 0


def run_auth_disable_user(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth disable-user <email|username|id>`` (P2).

    Soft-disable: sets ``disabled_at``; the row is kept for audit.
    The user's tokens stop working on the next request (D6-A, wired in P4).
    """
    from llmwikify.foundation.auth import UserRepository

    if _require_admin() is None:
        return 1

    spec = (getattr(args, "user", "") or "").strip()
    if not spec:
        print("[!] Usage: llmwikify auth disable-user <email|username|id>",
              file=sys.stderr)
        return 1

    repo = UserRepository()
    target = _resolve_user_spec(repo, spec)
    if target is None:
        print(f"[!] No user matching {spec!r}.", file=sys.stderr)
        return 1
    if target.is_first_admin:
        print("[!] Refusing to disable the admin (would lock you out).",
              file=sys.stderr)
        return 1

    if repo.disable(target.id):
        print(f"✓ Disabled {target.email}")
    else:
        print(f"· {target.email} was already disabled.")
    return 0


def run_auth_enable_user(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth enable-user <email|username|id>`` (P2, inverse)."""
    from llmwikify.foundation.auth import UserRepository

    if _require_admin() is None:
        return 1

    spec = (getattr(args, "user", "") or "").strip()
    if not spec:
        print("[!] Usage: llmwikify auth enable-user <email|username|id>",
              file=sys.stderr)
        return 1

    repo = UserRepository()
    target = _resolve_user_spec(repo, spec)
    if target is None:
        print(f"[!] No user matching {spec!r}.", file=sys.stderr)
        return 1

    if repo.enable(target.id):
        print(f"✓ Enabled {target.email}")
    else:
        print(f"· {target.email} was already active.")
    return 0


# ─── P3: grant / revoke / can-i (admin-only, Q4) ──────────────


def run_auth_grant(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth grant (--user U | --group G) --wiki W [--write]`` (P3).

    Upserts one grant row. 缺省 ``read``；``--write`` 蕴含 read.
    ``--wiki '*'`` grants every wiki, including future ones (Q3-a / Q3-c).
    Exactly one of --user / --group (P3b).
    """
    from llmwikify.foundation.auth import AuthError, GrantRepository

    if _require_admin() is None:
        return 1

    subject = _grant_target(args)
    if subject is None:
        return 1
    kind, principal_id = subject

    wiki_id = (getattr(args, "wiki", "") or "").strip()
    if not wiki_id:
        print(
            "[!] Usage: llmwikify auth grant (--user <id> | --group <name>) "
            "--wiki <id|*> [--write]",
            file=sys.stderr,
        )
        return 1

    want_write = bool(getattr(args, "write", False))
    try:
        GrantRepository().grant(
            kind,
            principal_id,
            wiki_id,
            read=True,
            write=want_write,
            granted_by=_admin_id(),
        )
    except AuthError as exc:
        print(f"[!] {exc.detail}", file=sys.stderr)
        return 1

    mode = "read+write" if want_write else "read"
    label = _subject_label(kind, principal_id)
    print(f"✓ Granted {label} → {wiki_id} ({mode})")
    if kind == "group":
        n = len(GrantRepository().list_members(principal_id))
        print(f"  Affects {n} member(s); revoke takes effect next request.")
    else:
        print("  Note: existing tokens keep their snapshot; run "
              "`llmwikify auth token` as that user to refresh.")
    return 0


def run_auth_revoke_grant(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth revoke (--user U | --group G) --wiki W`` (P3/P3b)."""
    from llmwikify.foundation.auth import GrantRepository

    if _require_admin() is None:
        return 1

    subject = _grant_target(args)
    if subject is None:
        return 1
    kind, principal_id = subject

    wiki_id = (getattr(args, "wiki", "") or "").strip()
    if not wiki_id:
        print(
            "[!] Usage: llmwikify auth revoke (--user <id> | --group <name>) "
            "--wiki <id|*>",
            file=sys.stderr,
        )
        return 1

    label = _subject_label(kind, principal_id)
    if GrantRepository().revoke(kind, principal_id, wiki_id):
        print(f"✓ Revoked {label} → {wiki_id} "
              "(takes effect on the next request)")
        if kind == "group":
            n = len(GrantRepository().list_members(principal_id))
            print(f"  Affects {n} member(s).")
    else:
        print(f"· No grant for {label} → {wiki_id}.")
    return 0


def _subject_label(kind: str, principal_id: str) -> str:
    """Human label for a grant subject (email / username / group name)."""
    if kind == "user":
        from llmwikify.foundation.auth import UserRepository

        u = UserRepository().get_by_id(principal_id)
        return u.email if u is not None else principal_id
    grp = _resolve_group(principal_id)
    return grp["name"] if grp is not None else principal_id


def run_auth_can_i(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth can-i --user U --wiki W [--write]`` → yes/no (K8s)."""
    from llmwikify.foundation.auth import GrantRepository, UserRepository

    if _require_admin() is None:
        return 1

    user_spec = (getattr(args, "user", "") or "").strip()
    wiki_id = (getattr(args, "wiki", "") or "").strip()
    if not user_spec or not wiki_id:
        print(
            "[!] Usage: llmwikify auth can-i --user <email|id> --wiki <id|*> "
            "[--write]",
            file=sys.stderr,
        )
        return 1

    target = _resolve_user_spec(UserRepository(), user_spec)
    if target is None:
        print(f"[!] No user matching {user_spec!r}.", file=sys.stderr)
        return 1

    if target.is_first_admin:
        print("yes  (admin, implicit full access)")
        return 0

    can_read, can_write = GrantRepository().effective(target.id, wiki_id)
    need_write = bool(getattr(args, "write", False))
    ok = can_write if need_write else can_read
    print("yes" if ok else "no")
    return 0 if ok else 1


def _admin_id() -> str | None:
    """id of the current admin (for ``granted_by`` audit), or None."""
    user = _resolve_local_user()
    return user.id if user is not None else None


# ─── P3b: group management + --group grants (admin-only) ──────


def _resolve_group(spec: str) -> Any | None:
    """Look up a group by id, then by name."""
    from llmwikify.foundation.auth import GrantRepository

    repo = GrantRepository()
    # id?
    for g in repo.list_groups():
        if g["id"] == spec:
            return g
    # name?
    for g in repo.list_groups():
        if g["name"] == spec:
            return g
    return None


def run_auth_group_create(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth group create <name>`` (P3b)."""
    from llmwikify.foundation.auth import AuthError, GrantRepository

    if _require_admin() is None:
        return 1

    name = (getattr(args, "name", "") or "").strip()
    if not name:
        print("[!] Usage: llmwikify auth group create <name>", file=sys.stderr)
        return 1

    try:
        gid = GrantRepository().create_group(name)
    except AuthError as exc:
        print(f"[!] {exc.detail}", file=sys.stderr)
        return 1
    print(f"✓ Created group: {name} (id={gid})")
    return 0


def run_auth_group_list(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth group list`` — groups + member counts (P3b)."""
    from llmwikify.foundation.auth import GrantRepository

    if _require_admin() is None:
        return 1

    groups = GrantRepository().list_groups()
    if not groups:
        print("No groups found.")
        return 0

    print(f"{'ID':<14} {'Name':<24} {'Members':<8}")
    print("-" * 48)
    for g in groups:
        print(f"{g['id'][:12]:<14} {g['name']:<24} {g['member_count']:<8}")
    print()
    print(f"Total: {len(groups)} group(s)")
    return 0


def run_auth_group_add(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth group add <group> --user U`` (P3b, idempotent)."""
    from llmwikify.foundation.auth import GrantRepository, UserRepository

    if _require_admin() is None:
        return 1

    group_spec = (getattr(args, "group", "") or "").strip()
    user_spec = (getattr(args, "user", "") or "").strip()
    if not group_spec or not user_spec:
        print(
            "[!] Usage: llmwikify auth group add <group> --user <email|id>",
            file=sys.stderr,
        )
        return 1

    grp = _resolve_group(group_spec)
    if grp is None:
        print(f"[!] No group matching {group_spec!r}.", file=sys.stderr)
        return 1
    target = _resolve_user_spec(UserRepository(), user_spec)
    if target is None:
        print(f"[!] No user matching {user_spec!r}.", file=sys.stderr)
        return 1

    if GrantRepository().add_member(grp["id"], target.id):
        print(f"✓ Added {target.email} → {grp['name']}")
    else:
        print(f"· {target.email} is already in {grp['name']}.")
    return 0


def run_auth_group_remove(wiki: Any, config: dict, args: Any) -> int:
    """``llmwikify auth group remove <group> --user U`` (P3b)."""
    from llmwikify.foundation.auth import GrantRepository, UserRepository

    if _require_admin() is None:
        return 1

    group_spec = (getattr(args, "group", "") or "").strip()
    user_spec = (getattr(args, "user", "") or "").strip()
    if not group_spec or not user_spec:
        print(
            "[!] Usage: llmwikify auth group remove <group> --user <email|id>",
            file=sys.stderr,
        )
        return 1

    grp = _resolve_group(group_spec)
    if grp is None:
        print(f"[!] No group matching {group_spec!r}.", file=sys.stderr)
        return 1
    target = _resolve_user_spec(UserRepository(), user_spec)
    if target is None:
        print(f"[!] No user matching {user_spec!r}.", file=sys.stderr)
        return 1

    if GrantRepository().remove_member(grp["id"], target.id):
        print(f"✓ Removed {target.email} from {grp['name']}")
        print("  Group grants no longer apply to this user (next request).")
    else:
        print(f"· {target.email} was not in {grp['name']}.")
    return 0


def _grant_target(args: Any) -> tuple[str, str] | None:
    """Resolve grant/revoke subject → ``(kind, principal_id)`` or None.

    kind is ``"user"`` or ``"group"``. Prints the error itself on failure.
    Exactly one of --user / --group must be given (P3b).
    """
    from llmwikify.foundation.auth import GrantRepository, UserRepository

    user_spec = (getattr(args, "user", "") or "").strip()
    group_spec = (getattr(args, "group", "") or "").strip()
    if bool(user_spec) == bool(group_spec):
        print(
            "[!] Provide exactly one of --user or --group.",
            file=sys.stderr,
        )
        return None
    if user_spec:
        target = _resolve_user_spec(UserRepository(), user_spec)
        if target is None:
            print(f"[!] No user matching {user_spec!r}.", file=sys.stderr)
            return None
        return "user", target.id
    grp = _resolve_group(group_spec)
    if grp is None:
        print(f"[!] No group matching {group_spec!r}.", file=sys.stderr)
        return None
    # Touch the repo so a valid-but-empty group still resolves cleanly.
    GrantRepository().list_members(grp["id"])
    return "group", grp["id"]


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

    # P2: user lifecycle (admin-only)
    p_cu = auth_sub.add_parser(
        "create-user", help="Create a non-admin user (admin only)"
    )
    p_cu.add_argument("--email", required=True, help="Email of the new user")
    auth_sub.add_parser("list-users", help="List users (admin only)")
    p_du = auth_sub.add_parser(
        "disable-user", help="Soft-disable a user (admin only)"
    )
    p_du.add_argument("user", help="Email / username / id to disable")
    p_eu = auth_sub.add_parser(
        "enable-user", help="Re-enable a disabled user (admin only)"
    )
    p_eu.add_argument("user", help="Email / username / id to enable")

    # P3: grant / revoke / can-i (admin only)
    p_gr = auth_sub.add_parser(
        "grant", help="Grant wiki access to a user or group (admin only)"
    )
    p_gr.add_argument("--user", help="Email / username / id (mutually exclusive with --group)")
    p_gr.add_argument("--group", help="Group name or id (mutually exclusive with --user)")
    p_gr.add_argument(
        "--wiki", required=True, help="Wiki id, or '*' for all wikis"
    )
    p_gr.add_argument(
        "--write", action="store_true", help="Grant write (implies read)"
    )
    p_rv = auth_sub.add_parser(
        "revoke", help="Revoke a user's/group's wiki grant (admin only)"
    )
    p_rv.add_argument("--user", help="Email / username / id (mutually exclusive with --group)")
    p_rv.add_argument("--group", help="Group name or id (mutually exclusive with --user)")
    p_rv.add_argument(
        "--wiki", required=True, help="Wiki id, or '*' to drop the wildcard"
    )
    p_ci = auth_sub.add_parser(
        "can-i", help="Check whether a user can access a wiki (admin only)"
    )
    p_ci.add_argument("--user", required=True, help="Email / username / id")
    p_ci.add_argument("--wiki", required=True, help="Wiki id")
    p_ci.add_argument(
        "--write", action="store_true", help="Check write instead of read"
    )

    # P3b: group management (admin only)
    p_gc = auth_sub.add_parser("group", help="Group management (admin only)")
    group_sub = p_gc.add_subparsers(dest="group_command", help="Group subcommand")
    p_gcreate = group_sub.add_parser("create", help="Create a group")
    p_gcreate.add_argument("name", help="Group name")
    group_sub.add_parser("list", help="List groups with member counts")
    p_gadd = group_sub.add_parser("add", help="Add a user to a group")
    p_gadd.add_argument("group", help="Group name or id")
    p_gadd.add_argument("--user", required=True, help="Email / username / id")
    p_grm = group_sub.add_parser("remove", help="Remove a user from a group")
    p_grm.add_argument("group", help="Group name or id")
    p_grm.add_argument("--user", required=True, help="Email / username / id")


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
                "Usage: llmwikify auth {init,create-token,list-tokens,"
                "revoke-token,token,whoami,logout,"
                "create-user,list-users,disable-user,enable-user,"
                "grant,revoke,can-i,group}",
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
        if sub == "create-user":
            return run_auth_create_user(wiki, config, args)
        if sub == "list-users":
            return run_auth_list_users(wiki, config, args)
        if sub == "disable-user":
            return run_auth_disable_user(wiki, config, args)
        if sub == "enable-user":
            return run_auth_enable_user(wiki, config, args)
        if sub == "grant":
            return run_auth_grant(wiki, config, args)
        if sub == "revoke":
            return run_auth_revoke_grant(wiki, config, args)
        if sub == "can-i":
            return run_auth_can_i(wiki, config, args)
        if sub == "group":
            return _dispatch_group(wiki, config, args)
        print(f"Unknown auth subcommand: {sub}", file=sys.stderr)
        return 1


def _dispatch_group(wiki: Any, config: dict, args: Any) -> int:
    """Dispatch ``auth group <create|list|add|remove>`` (P3b)."""
    sub = getattr(args, "group_command", None)
    if sub == "create":
        return run_auth_group_create(wiki, config, args)
    if sub == "list":
        return run_auth_group_list(wiki, config, args)
    if sub == "add":
        return run_auth_group_add(wiki, config, args)
    if sub == "remove":
        return run_auth_group_remove(wiki, config, args)
    print(
        "Usage: llmwikify auth group {create,list,add,remove}",
        file=sys.stderr,
    )
    return 1
