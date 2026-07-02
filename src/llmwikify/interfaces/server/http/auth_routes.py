"""HTTP auth routes — PAT-based authentication (decision 25).

Layer: L4 (interfaces/server/http). No fastapi-login dependency.

Endpoints:
  POST /auth/register   { email }              -> 200 { pat, user }
  POST /auth/verify     { pat }                -> 200 { access_token, user }
  POST /auth/tokens     { name }               -> 200 { pat, key }       (authenticated)
  GET  /auth/tokens                               -> 200 { keys }         (authenticated)
  DELETE /auth/tokens/{id}                         -> 200 { ok }          (authenticated)
  GET  /auth/me                                    -> 200 { user }        (authenticated)

Error response format: decision 10 — JSON {error, status_code, detail}.

Decisions cross-referenced:
  - 1  /me returns `{can_edit, wikis}` not raw scope
  - 10 error format = JSON
  - 12 in local mode /me still returns the local trust info
  - 25 PAT replaces passwords
  - 26 PAT format = llmw_ prefix + 24-byte hex
  - 27 api_keys table stores SHA-256 hash
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from llmwikify.foundation.auth import (
    ApiKeyRepository,
    TokenClaims,
    UserRepository,
    auth_db_path,
    decode,
    encode,
    env_host,
    generate_pat,
    hash_pat,
    is_local_default,
    require_secret,
    verify_pat,
)

logger = logging.getLogger(__name__)


COOKIE_NAME = "llmwikify_token"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30d, matches owner JWT TTL


def _get_jwt_secret() -> bytes:
    return require_secret()


def _build_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/register")
    async def register(request: Request) -> dict[str, Any]:
        """Create a new user + issue a PAT.

        Body: { "email": "user@example.com" }
        Returns: { "pat": "llmw_xxx...", "user": { ... } }

        In local mode with no auth.db, creates the first admin.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={"error": "invalid_json", "detail": "Request body must be JSON."})

        email = (body.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_email", "detail": "A valid email is required."},
            )

        repo = UserRepository()
        host = _resolve_effective_host(request)
        local_mode = is_local_default(host)

        # In local mode with no existing user, create first admin.
        is_first = not repo.exists()

        if repo.get_by_email(email) is not None:
            raise HTTPException(
                status_code=409,
                detail={"error": "email_taken", "detail": f"User with email {email!r} already exists."},
            )

        user = repo.create(email=email, is_first_admin=is_first)

        # Generate PAT.
        pat, pat_hash = generate_pat()
        ak_repo = ApiKeyRepository()
        ak_repo.create(
            user_id=user.id,
            key_prefix=pat[:12],
            key_hash=pat_hash,
            name="webui-default",
            scopes="write",
        )

        # Build JWT for immediate use.
        wikis = _list_wikis_from_registry(request)
        claims = TokenClaims.new(
            sub=f"user:{user.id}",
            scope="write",
            wikis=wikis or ["*"],
        )
        token = encode(claims, _get_jwt_secret())

        return {
            "pat": pat,
            "access_token": token,
            "user": _user_to_dict(user, claims, local_mode=local_mode),
        }

    @router.post("/verify")
    async def verify_token(request: Request, response: Response) -> dict[str, Any]:
        """Verify a PAT and return a short-lived JWT.

        Body: { "pat": "llmw_xxx..." }
        Returns: { "access_token": "...", "user": { ... } }

        WebUI uses this to exchange a PAT (stored in localStorage)
        for a JWT (stored in authStore + cookie).
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={"error": "invalid_json", "detail": "Request body must be JSON."})

        pat = (body.get("pat") or "").strip()
        if not pat:
            raise HTTPException(
                status_code=400,
                detail={"error": "missing_pat", "detail": "PAT is required."},
            )

        # Lookup by hash.
        pat_hash = hash_pat(pat)
        ak_repo = ApiKeyRepository()
        api_key = ak_repo.get_by_hash(pat_hash)
        if api_key is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_pat", "detail": "Invalid or revoked PAT."},
            )

        # Touch last_used_at (best-effort).
        try:
            ak_repo.touch_last_used(api_key.id)
        except Exception:
            logger.warning("failed to touch last_used_at for api_key %s", api_key.id, exc_info=True)

        # Resolve user.
        repo = UserRepository()
        user = repo.get_by_id(api_key.user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "user_not_found", "detail": "PAT owner no longer exists."},
            )

        # Issue JWT.
        wikis = _list_wikis_from_registry(request)
        claims = TokenClaims.new(
            sub=f"user:{user.id}",
            scope=api_key.scopes,
            wikis=wikis or ["*"],
        )
        token = encode(claims, _get_jwt_secret())

        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )

        return {
            "access_token": token,
            "expires_at": datetime.fromtimestamp(claims.exp, tz=timezone.utc).isoformat(),
            "user": _user_to_dict(user, claims, local_mode=False),
        }

    @router.post("/tokens")
    async def create_token(request: Request) -> dict[str, Any]:
        """Create a new PAT for the authenticated user.

        Body: { "name": "laptop" }
        Returns: { "pat": "llmw_xxx...", "key": { id, prefix, name, ... } }

        The PAT is shown once. Store it securely.
        """
        claims = _require_auth(request)
        user_id = claims.sub[len("user:"):]
        body = await request.json()
        name = (body.get("name") or "unnamed").strip()

        pat, pat_hash = generate_pat()
        ak_repo = ApiKeyRepository()
        ak = ak_repo.create(
            user_id=user_id,
            key_prefix=pat[:12],
            key_hash=pat_hash,
            name=name,
            scopes="write",
        )

        return {
            "pat": pat,
            "key": {
                "id": ak.id,
                "prefix": ak.key_prefix,
                "name": ak.name,
                "scopes": ak.scopes,
                "created_at": ak.created_at,
            },
        }

    @router.get("/tokens")
    async def list_tokens(request: Request) -> dict[str, Any]:
        """List all PATs for the authenticated user."""
        claims = _require_auth(request)
        user_id = claims.sub[len("user:"):]
        ak_repo = ApiKeyRepository()
        keys = ak_repo.list_by_user(user_id)
        return {
            "keys": [
                {
                    "id": k.id,
                    "prefix": k.key_prefix,
                    "name": k.name,
                    "scopes": k.scopes,
                    "created_at": k.created_at,
                    "last_used_at": k.last_used_at,
                    "expires_at": k.expires_at,
                    "revoked_at": k.revoked_at,
                }
                for k in keys
            ],
        }

    @router.delete("/tokens/{key_id}")
    async def revoke_token(key_id: str, request: Request) -> dict[str, Any]:
        """Revoke a PAT."""
        claims = _require_auth(request)
        user_id = claims.sub[len("user:"):]
        ak_repo = ApiKeyRepository()
        ak = ak_repo.get_by_id(key_id)
        if ak is None or ak.user_id != user_id:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "detail": "API key not found."},
            )
        ak_repo.revoke(key_id)
        return {"ok": True}

    @router.get("/me")
    async def me(
        request: Request,
        llmwikify_token: str | None = Cookie(default=None),
    ) -> dict[str, Any]:
        """Return identity of current user (or local-mode marker)."""
        host = _resolve_effective_host(request)
        local_mode = is_local_default(host)

        if not llmwikify_token:
            if local_mode:
                return {
                    "authenticated": False,
                    "user": {
                        "email": "local@host",
                        "is_first_admin": True,
                        "can_edit": True,
                        "wikis": ["*"],
                        "local_mode": True,
                    },
                }
            raise HTTPException(
                status_code=401,
                detail={"error": "not_authenticated", "detail": "No session cookie. POST /auth/verify first."},
            )

        if llmwikify_token == "local-mode-no-auth":
            return {
                "authenticated": True,
                "user": {
                    "email": "local@host",
                    "is_first_admin": True,
                    "can_edit": True,
                    "wikis": ["*"],
                    "local_mode": True,
                },
            }

        try:
            claims = decode(llmwikify_token, _get_jwt_secret())
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_token", "detail": f"Token invalid: {type(exc).__name__}"},
            )

        if not claims.sub.startswith("user:"):
            raise HTTPException(
                status_code=401,
                detail={"error": "share_token_not_here", "detail": "/auth/me is owner-only."},
            )

        user_id = claims.sub[len("user:"):]
        user = UserRepository().get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "user_not_found", "detail": "Token refers to a deleted user."},
            )
        return {
            "authenticated": True,
            "user": _user_to_dict(user, claims, local_mode=False),
        }

    return router


# ─── helpers ─────────────────────────────────────────────────────


def _require_auth(request: Request) -> TokenClaims:
    """Extract and validate JWT from request. Raises 401 on failure."""
    claims = getattr(request.state, "auth_claims", None)
    if claims is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "not_authenticated", "detail": "Authentication required."},
        )
    return claims


def _user_to_dict(user, claims: TokenClaims, *, local_mode: bool) -> dict[str, Any]:
    return {
        "email": user.email if not local_mode else "local@host",
        "is_first_admin": user.is_first_admin if not local_mode else True,
        "can_edit": claims.scope == "write",
        "wikis": list(claims.wikis),
        "local_mode": local_mode,
    }


def _list_wikis_from_registry(request: Request) -> list[str]:
    registry = getattr(request.app.state, "wiki_registry", None)
    if registry is None:
        return ["*"]
    try:
        wikis = registry.list_wikis()
    except Exception:
        return ["*"]
    return [w.wiki_id for w in wikis] or ["*"]


def _resolve_effective_host(request: Request) -> str:
    try:
        host = request.url.hostname or ""
    except Exception:
        host = ""
    return host or env_host()


auth_router = _build_router()
