"""Request authorization decision (P4a) — one pure-ish entry point.

Layer: L1 (foundation). Zero deps on apps/kernel/interfaces.

Design: ``docs/designs/multiuser-auth-design.md`` §12.5. The decision
order is fixed and short-circuiting::

    ④ disabled_at          → 401
    scope ceiling          → 403   (non-GET needs claims.scope == "write")
    ⑤ is_first_admin       → allow (PG owner, design §5.2)
    wiki_id is None        → allow (non-wiki route; only scope matters)
    ⑥' legacy token        → allow iff claims.wikis covers the wiki
    ⑥  live wiki_grants    → deny if no row; fail-closed on query error
    ⑦  snapshot ∩ live     → deny if wiki absent from claims.wgrants

Legacy rule (P4a, value-based — no schema change):
    ``wgrants`` empty **and** ``wikis`` non-empty  →  pre-P3 token
    (P3 signing always set ``wikis=["*"]``); the ``wikis`` list governs
    and ``scope`` still applies (old non-admin tokens stay read-only).
    ``wgrants`` empty **and** ``wikis == []``      →  new zero-grant
    token (D8) — falls through to the live check, which denies.

User-missing is a **401** (P4b): a token for a deleted account dies with
the account. The check runs after the pure scope ceiling so a
read-only token on a missing user still reports ``forbidden_scope``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ._jwt import TokenClaims

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthzDecision:
    """Outcome of :func:`authorize_request`."""

    allowed: bool
    status: int = 200
    code: str = ""
    detail: str = ""


def _allow() -> AuthzDecision:
    return AuthzDecision(True, 200, "", "")


def _deny(status: int, code: str, detail: str) -> AuthzDecision:
    return AuthzDecision(False, status, code, detail)


def _wiki_denied(wiki_id: str, allowed: str) -> AuthzDecision:
    return _deny(
        403,
        "forbidden_wiki",
        f"Token does not cover wiki {wiki_id!r}. Allowed: {allowed}. "
        "Re-run `llmwikify auth token` to refresh.",
    )


def authorize_request(
    claims: TokenClaims,
    *,
    wiki_id: str | None,
    need_write: bool,
    db_path: Path | None = None,
) -> AuthzDecision:
    """Decide whether a verified token may perform this request.

    Args:
        claims: Decoded token (already signature-verified by the caller).
        wiki_id: Target wiki for ``/api/wiki/{id}/...`` routes; ``None``
            for routes that are not wiki-scoped (only scope applies).
        need_write: True for non-GET methods (decision 4).
        db_path: Optional auth.db override (tests).

    Returns:
        :class:`AuthzDecision` — check ``allowed`` then map ``status``/
        ``code``/``detail`` onto the HTTP error body.
    """
    # Subject must be a user (share tokens are rejected here; /auth/me
    # has its own message).
    if not claims.sub.startswith("user:"):
        return _deny(
            401,
            "invalid_subject",
            "Only user tokens are accepted on this route.",
        )
    user_id = claims.sub[len("user:") :]

    # Load the user once (disabled + admin both need it). A missing row
    # is NOT an error in P4a — see module docstring.
    from .db import UserRepository

    user = UserRepository(db_path=db_path).get_by_id(user_id)

    # Global scope ceiling (decision 4): non-GET requires write.
    # Checked before the user-exists probe so a read-only token on a
    # missing user still reports forbidden_scope (cheaper, more precise).
    if need_write and claims.scope != "write":
        return _deny(
            403,
            "forbidden_scope",
            f"scope=write required; got {claims.scope!r}",
        )

    # P4b: the user must still exist (deleted account → token dies too).
    if user is None:
        return _deny(
            401,
            "user_not_found",
            "Token refers to a deleted user.",
        )

    # ④ disabled (D6: takes effect on the very next request)
    if user.disabled_at is not None:
        return _deny(401, "user_disabled", "User account is disabled.")

    # ⑤ admin → implicit full access (PG owner). Checked before the
    # wiki dimension so admins see wikis created after signing.
    if user.is_first_admin:
        return _allow()

    # Non-wiki route: only scope (and disabled) apply.
    if wiki_id is None:
        return _allow()

    # ⑥' legacy token (P4a): no per-wiki snapshot → the ``wikis`` list
    # governs. Real pre-P3 tokens carry ["*"] → full wiki access.
    if not claims.wgrants and claims.wikis:
        if "*" in claims.wikis or wiki_id in claims.wikis:
            return _allow()
        return _wiki_denied(wiki_id, repr(claims.wikis))

    # ⑥ live upper bound (D6-A / D7): reflects the current grants table,
    # so a revoke or a disable is visible immediately.
    from .grants import GrantRepository

    try:
        can_read, can_write = GrantRepository(db_path=db_path).effective(
            user_id, wiki_id
        )
    except Exception:  # noqa: BLE001 — M4 fail-closed
        logger.warning(
            "authz query failed for user=%s wiki=%s", user_id, wiki_id, exc_info=True
        )
        return _deny(
            403,
            "authz_unavailable",
            "Authorization data unavailable; request denied.",
        )
    if need_write and not can_write:
        return _wiki_denied(wiki_id, "read-only (no write grant)")
    if not need_write and not can_read:
        return _wiki_denied(wiki_id, "no read grant")

    # ⑦ snapshot ∩ live (D7): grants added after signing are NOT
    # retroactive; a wiki absent from the snapshot requires re-signing.
    snap = claims.wgrants.get(wiki_id)
    if snap is None:
        return _deny(
            403,
            "forbidden_wiki",
            f"Wiki {wiki_id!r} is not in this token's snapshot. "
            "Re-run `llmwikify auth token` to refresh.",
        )
    if need_write and snap != "rw":
        return _deny(
            403,
            "forbidden_wiki",
            f"Token snapshot grants read-only on {wiki_id!r}.",
        )
    return _allow()


def accessible_wikis(
    claims: TokenClaims,
    known_wikis: list[str],
    db_path: Path | None = None,
) -> set[str]:
    """Wikis this token can READ — snapshot ∩ live (P4b, list routes).

    ``/api/wikis`` and ``/api/search/cross`` return *lists*; they must
    show exactly the wikis a point-read would be allowed on, otherwise
    the UI lists a wiki that 403s on open.

    Rules mirror :func:`authorize_request`:

    * admin → every known wiki
    * legacy token (``wgrants`` empty + ``wikis`` non-empty) → the
      ``wikis`` list (``*`` = all known) — no live check, same as the
      point-read path
    * new token → readable keys of ``wgrants`` ∩ known ∩ live ``expand()``
    * missing user / non-user subject → empty set
    """
    known = set(known_wikis)
    if not claims.sub.startswith("user:"):
        return set()
    user_id = claims.sub[len("user:") :]

    from .db import UserRepository

    user = UserRepository(db_path=db_path).get_by_id(user_id)
    if user is None:
        return set()
    if user.is_first_admin:
        return known

    # Legacy token: the wikis list is the whole story.
    if not claims.wgrants and claims.wikis:
        if "*" in claims.wikis:
            return known
        return set(claims.wikis) & known

    # New token: snapshot readable keys, then confirm against live grants.
    readable_snap = {
        w for w, v in claims.wgrants.items() if v in ("r", "rw")
    }
    candidates = readable_snap & known
    if not candidates:
        return set()
    from .grants import GrantRepository

    try:
        live = GrantRepository(db_path=db_path).expand(user_id, candidates)
    except Exception:  # noqa: BLE001 — fail-closed
        logger.warning(
            "accessible_wikis expand failed for user=%s", user_id, exc_info=True
        )
        return set()
    return {w for w in candidates if live.get(w, (False, False))[0]}


__all__ = ["AuthzDecision", "authorize_request", "accessible_wikis"]
