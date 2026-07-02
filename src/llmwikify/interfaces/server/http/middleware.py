"""HTTP middleware components."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

import jwt as _pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from llmwikify.foundation.auth import (
    AuthError,
    TokenClaims,
    decode,
    hash_pat,
    is_local_default,
    require_secret,
    verify_pat,
)
from llmwikify.foundation.auth.db import ApiKeyRepository, UserRepository
from llmwikify.interfaces.server.constants import (
    EXCLUDED_AUTH_PATHS,
    EXCLUDED_AUTH_PREFIXES,
)

logger = logging.getLogger(__name__)


# Phase 4.3 (v0.36): token-bucket rate limiter.
# Default: 60 requests per minute per IP. Configurable via
# RATE_LIMIT_PER_MIN env var (set to 0 to disable).


def _parse_rate_limit() -> int:
    """Parse RATE_LIMIT_PER_MIN env var. Returns 0 if disabled."""
    raw = os.environ.get("RATE_LIMIT_PER_MIN", "60")
    try:
        return max(0, int(raw))
    except ValueError:
        return 60


RATE_LIMIT_PER_MIN = _parse_rate_limit()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter per IP address.

    Applied only to /api/agent/* routes. Returns 429 with a
    Retry-After header when the bucket is empty.

    Usage::

        app.add_middleware(RateLimitMiddleware)

    Disable by setting env var RATE_LIMIT_PER_MIN=0.
    """

    def __init__(self, app, limit_per_min: int = RATE_LIMIT_PER_MIN):
        super().__init__(app)
        self.limit_per_min = limit_per_min
        # Buckets: ip -> (tokens: float, last_refill: float)
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (float(limit_per_min), time.monotonic())
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only rate-limit agent API routes.
        path = request.url.path
        if not path.startswith("/api/agent"):
            return await call_next(request)

        if self.limit_per_min <= 0:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        tokens, last_refill = self._buckets[client_ip]

        # Refill tokens based on elapsed time.
        elapsed = now - last_refill
        refill = elapsed * (self.limit_per_min / 60.0)
        tokens = min(self.limit_per_min, tokens + refill)
        self._buckets[client_ip] = (tokens, now)

        if tokens < 1.0:
            retry_after = int((1.0 - tokens) * 60 / self.limit_per_min) + 1
            return JSONResponse(
                {
                    "error": "Rate limit exceeded",
                    "retry_after": retry_after,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        self._buckets[client_ip] = (tokens - 1.0, now)
        return await call_next(request)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT-based auth middleware with scope + local-mode bypass.

    Replaces the previous `AuthMiddleware` (static API-key check).

    Verifies requests using (in priority order):
      1. httpOnly cookie ``llmwikify_token`` (browser path)
      2. ``Authorization: Bearer <token>`` (CLI/curl)
      3. ``?token=<X>`` query param (legacy static-key fallback only;
         JWT-in-query-param is intentionally NOT supported because
         it leaks via referer logs — see decision 1 + Phase 3 share
         for proper share-token handling)

    Decisions enforced:
      - 1   GET  (read)  + public_read=True  + no token    → 200
                  POST (write) + no token                    → 403
      - 4   scope based on HTTP method (GET=read, others=write)
      - 6   cookie secure=False (MVP) — TLS termination
                expected at reverse proxy in production
      - 7   wikis claim validated per-request against path
                /api/wiki/{wiki_id}/...
      - 12  local mode (loopback bind) → middleware is a
                pass-through: anyone on localhost is fully trusted,
                including POST/PUT/DELETE
    """

    def __init__(
        self,
        app,
        *,
        secret: bytes | None = None,
        public_read: bool = True,
        local_mode: bool = False,
    ) -> None:
        super().__init__(app)
        # Secret is loaded lazily (and lazily fetched) so that servers
        # that never need to verify a token (pure local-mode, no cookie)
        # don't crash at boot if the keyring isn't ready yet.
        self._explicit_secret = secret
        self.public_read = public_read
        self.local_mode = local_mode

    def _get_secret(self) -> bytes:
        if self._explicit_secret is not None:
            return self._explicit_secret
        return require_secret()

    def _is_excluded(self, path: str) -> bool:
        if path in EXCLUDED_AUTH_PATHS:
            return True
        for prefix in EXCLUDED_AUTH_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if self._is_excluded(path):
            return await call_next(request)

        # Local-mode bypass (decision 12): anyone on localhost is fully
        # trusted. We never block writes here. The serve.py controller
        # is responsible for setting local_mode based on the bind host.
        if self.local_mode:
            return await call_next(request)

        # Try to extract token from cookie or Authorization header.
        token = self._extract_token(request)
        if not token:
            # No token at all. Allow GETs if public_read, else 401/403.
            if request.method == "GET" and self.public_read:
                return await call_next(request)
            return _deny_no_token(request.method, self.public_read)

        # Token present — verify (JWT first, then PAT fallback).
        claims = self._verify_token(token)
        if claims is None:
            return _deny(401, "invalid_token", "Token is invalid or expired.")

        # Scope enforcement (decision 4): non-GET requires scope=write.
        if request.method != "GET" and claims.scope != "write":
            return _deny(403, "forbidden_scope", f"scope=write required; got {claims.scope!r}")

        # Wikis claim enforcement (decision 7): for /api/wiki/{wiki_id}/...
        # paths, check that the token covers this wiki.
        wiki_violation = _check_wikis_claim(path, claims)
        if wiki_violation is not None:
            return _deny(403, "forbidden_wiki", wiki_violation)

        # Attach claims to request.state so downstream handlers can read.
        request.state.auth_claims = claims
        return await call_next(request)

    def _extract_token(self, request: Request) -> str:
        """Read token from cookie (preferred) or Authorization header."""
        cookie_token = request.cookies.get("llmwikify_token")
        if cookie_token:
            return cookie_token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""

    def _verify_token(self, token: str) -> TokenClaims | None:
        """Try JWT decode first, then PAT lookup. Returns claims or None."""
        # 1. Try JWT.
        try:
            return decode(token, self._get_secret())
        except _pyjwt.ExpiredSignatureError:
            pass  # expired JWT — fall through to PAT
        except _pyjwt.InvalidTokenError:
            pass  # not a valid JWT — might be a PAT
        except AuthError:
            pass

        # 2. Try PAT lookup (SHA-256 hash in api_keys table).
        try:
            pat_hash = hash_pat(token)
            ak_repo = ApiKeyRepository()
            api_key = ak_repo.get_by_hash(pat_hash)
            if api_key is None:
                return None

            # Touch last_used_at (best-effort).
            try:
                ak_repo.touch_last_used(api_key.id)
            except Exception:
                logger.warning("failed to touch last_used_at for api_key %s", api_key.id, exc_info=True)

            # Resolve user to build claims.
            user = UserRepository().get_by_id(api_key.user_id)
            if user is None:
                return None

            return TokenClaims.new(
                sub=f"user:{user.id}",
                scope=api_key.scopes,
                wikis=["*"],
            )
        except Exception:
            logger.debug("PAT lookup failed", exc_info=True)
            return None


# ─── helpers ─────────────────────────────────────────────────────


def _deny(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"error": code, "status_code": status_code, "detail": detail},
        status_code=status_code,
    )


def _deny_no_token(method: str, public_read: bool) -> JSONResponse:
    """Special-case 401 vs 403 for unauthenticated requests.

    401 Unauthorized: no token AND public_read=False (always require
                      auth, even for reads).
    403 Forbidden:   no token AND public_read=True  (GET would have
                      been allowed, but the caller is doing a non-GET
                      so we forbid).
    """
    if not public_read:
        return _deny(401, "auth_required", "Authentication required.")
    if method == "GET":
        # Should not reach here in normal flow (GET bypassed above),
        # but be defensive.
        return _deny(401, "auth_required", "Authentication required.")
    return _deny(403, "auth_required", f"{method} requires authentication; POST /auth/login first.")


def _check_wikis_claim(path: str, claims: TokenClaims) -> str | None:
    """If the path is /api/wiki/{wiki_id}/..., enforce the wikis claim.

    Returns None on pass, an error message on fail.
    """
    if not path.startswith("/api/wiki/"):
        return None
    # Split off the wiki id. Format: /api/wiki/{wiki_id}/...
    parts = path.split("/")
    # parts = ['', 'api', 'wiki', '{wiki_id}', ...]
    if len(parts) < 4 or not parts[3]:
        return None
    wiki_id = parts[3]
    # Wildcard "*" is the bootstrap owner token; allow everything.
    if "*" in claims.wikis:
        return None
    if wiki_id in claims.wikis:
        return None
    return (
        f"Token does not cover wiki {wiki_id!r}. "
        f"Allowed: {claims.wikis!r}. Re-run `llmwikify auth token` to refresh."
    )
