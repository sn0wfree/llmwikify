"""HTTP auth routes — POST /auth/login, GET /auth/me.

Layer: L4 (interfaces/server/http). Uses fastapi-login (decision 17) to
mechanically handle the JWT-in-cookie dance; we keep the
application-specific bits (scope/wikis/public_read/local-mode)
inside our own JWTAuthMiddleware.

Endpoints:
  POST /auth/login    { email, password }    -> 200 { access_token, user }
                                                 + Set-Cookie: llmwikify_token
  GET  /auth/me        (no body)              -> 200 { email, is_first_admin,
                                                            can_edit, wikis }

Error response format: decision 10 — JSON {error, status_code, detail}.

Decisions cross-referenced:
  - 1  /me returns `{can_edit, wikis}` not raw scope
  - 3  Login sets httpOnly cookie; the response body also returns
        access_token for CLI/curl use (the body token is identical
        to what's in the cookie)
  - 6  cookie secure=False in MVP (HTTPS not required locally)
  - 10 error format = JSON
  - 12 in local mode /me still returns the local trust info
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from llmwikify.foundation.auth import (
    TokenClaims,
    UserRepository,
    auth_db_path,
    decode,
    encode,
    env_host,
    is_local_default,
    require_secret,
    verify_password,
)

logger = logging.getLogger(__name__)


# Cookie name is namespaced under the package to avoid clashes with other
# apps on the same host.
COOKIE_NAME = "llmwikify_token"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30d, matches owner JWT TTL


def _get_jwt_secret() -> bytes:
    """Read the JWT signing secret. Hard-fails if not initialized."""
    return require_secret()


def _build_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    async def login(
        request: Request,
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends(),  # noqa: B008
    ) -> dict[str, Any]:
        """Verify password, issue JWT, set httpOnly cookie.

        Body params (OAuth2PasswordRequestForm):
            username:  actually the email (OAuth2 form spec uses
                      `username` for the principal name; we treat it
                      as email since that's our unique identifier)
            password:  the cleartext password

        In `local mode` (decision 12), if no auth.db exists yet, we
        still allow login as a synthetic "local user" — no actual
        authentication happens. This mirrors the local-trust posture.
        """
        repo = UserRepository()
        host = _resolve_effective_host(request)
        local_mode = is_local_default(host)
        if not repo.exists() and local_mode:
            # No auth.db in local mode: synthesize a virtual owner.
            # We can't sign a real JWT without a keyring secret, so
            # we return a no-op token + a marker in the body.
            response.set_cookie(
                key=COOKIE_NAME,
                value="local-mode-no-auth",
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=False,
                path="/",
            )
            return {
                "access_token": "local-mode-no-auth",
                "expires_at": None,
                "user": {
                    "email": "local@host",
                    "is_first_admin": True,
                    "can_edit": True,
                    "wikis": ["*"],
                    "local_mode": True,
                },
            }

        user = repo.get_by_email(form_data.username)
        if user is None or not verify_password(form_data.password, user.password_hash):
            # Generic message: don't reveal whether the email exists.
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "invalid_credentials",
                    "status_code": 401,
                    "detail": "Invalid email or password.",
                },
            )

        # Build claims.
        wikis = _list_wikis_from_registry(request)
        claims = TokenClaims.new(
            sub=f"user:{user.id}",
            scope="write",
            wikis=wikis or ["*"],
        )
        token = encode(claims, _get_jwt_secret())

        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=False,  # decision 6: MVP
            path="/",
        )
        # touch last login (best-effort, don't block response)
        try:
            repo.touch_last_login(user.id)
        except Exception:  # pragma: no cover - best effort
            logger.warning("failed to touch last_login_at for %s", user.id, exc_info=True)

        return {
            "access_token": token,
            "expires_at": datetime.fromtimestamp(claims.exp, tz=timezone.utc).isoformat(),
            "user": _user_to_dict(user, claims, local_mode=False),
        }

    @router.get("/me")
    async def me(
        request: Request,
        llmwikify_token: str | None = Cookie(default=None),  # noqa: B008
    ) -> dict[str, Any]:
        """Return identity of current user (or local-mode marker).

        Decision 1: response body is the user-friendly shape, not
        the raw scope string. The raw claims never leave the server.
        """
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
                detail={
                    "error": "not_authenticated",
                    "status_code": 401,
                    "detail": "No session cookie present. POST /auth/login first.",
                },
            )

        if llmwikify_token == "local-mode-no-auth":
            # Server was in local-mode-no-auth at login time. Mirror that
            # here so the client gets a consistent shape.
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
        except Exception as exc:  # jwt.ExpiredSignatureError, etc.
            logger.info("/auth/me: token decode failed: %s", exc)
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "invalid_token",
                    "status_code": 401,
                    "detail": f"Token is invalid or expired: {type(exc).__name__}",
                },
            )

        # Resolve user from sub. We don't expose the raw sub in the
        # response; we look up the user record and return friendly fields.
        if not claims.sub.startswith("user:"):
            # Phase 3: this is a share token. /me is only meaningful for
            # owner; for share we'd return 401 in the user-friendly shape
            # and have the WebUI redirect to /share/{slug} instead.
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "share_token_not_here",
                    "status_code": 401,
                    "detail": "/auth/me is owner-only; use the share URL directly.",
                },
            )
        user_id = claims.sub[len("user:"):]
        user = UserRepository().get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "user_not_found",
                    "status_code": 401,
                    "detail": "Token refers to a user that no longer exists.",
                },
            )
        return {
            "authenticated": True,
            "user": _user_to_dict(user, claims, local_mode=False),
        }

    return router


def _user_to_dict(user, claims: TokenClaims, *, local_mode: bool) -> dict[str, Any]:
    """Map a User + TokenClaims to the friendly /me response shape."""
    return {
        "email": user.email if not local_mode else "local@host",
        "is_first_admin": user.is_first_admin if not local_mode else True,
        # Decision 1: expose can_edit + wikis, not raw scope.
        "can_edit": claims.scope == "write",
        "wikis": list(claims.wikis),
        "local_mode": local_mode,
    }


def _list_wikis_from_registry(request: Request) -> list[str]:
    """Try to read the WikiRegistry from app state. Return [] if not present.

    The middleware stores `app.state.wiki_registry` when it sets up. If
    the route is hit before the registry is built (e.g. test fixtures),
    we fall back to ["*"] for the bootstrap token.
    """
    registry = getattr(request.app.state, "wiki_registry", None)
    if registry is None:
        return ["*"]
    try:
        wikis = registry.list_wikis()
    except Exception:  # pragma: no cover - defensive
        return ["*"]
    return [w.wiki_id for w in wikis] or ["*"]


def _resolve_effective_host(request: Request) -> str:
    """What host is the request coming in on?

    For local-mode detection we use the request URL's host. Falls back
    to env_host() if request.url.hostname is None.
    """
    try:
        host = request.url.hostname or ""
    except Exception:
        host = ""
    return host or env_host()


# Module-level singleton for FastAPI's `app.include_router(auth_router)`.
auth_router = _build_router()
