"""HTTP middleware components."""

from __future__ import annotations

import ipaddress
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import jwt as _pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from llmwikify.foundation.auth import (
    AuthError,
    TokenClaims,
    decode,
    hash_pat,
    require_secret,
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

# Maximum number of IP buckets to keep in memory (prevents DoS)
MAX_BUCKETS = 10000

# ─── Trusted proxy / real client IP helpers ────────────────────────


def _load_trusted_proxies() -> list[str]:
    """Load trusted proxy networks from config.

    Returns:
        List of IP networks/addresses (e.g. ['127.0.0.1', '10.0.0.0/8']).
        Empty list = no trusted proxies = fall back to direct TCP peer.
    """
    try:
        # 2026-10-14 fix: `get_config` never existed in foundation.config —
        # the ImportError was silently swallowed by the except below, so
        # trusted_proxies has been dead code since its introduction. Use
        # the module's actual singleton (foundation.config.config).
        from llmwikify.foundation.config import config as _llmwikify_config

        cfg = _llmwikify_config.get()
        server_cfg = cfg.get("server", {})
        proxies = server_cfg.get("trusted_proxies", None)
        if proxies is None:
            return []
        if isinstance(proxies, list):
            return [str(p).strip() for p in proxies]
        return []
    except Exception:
        logger.debug("Failed to load trusted_proxies config", exc_info=True)
        return []


_TRUSTED_PROXY_CACHE: list[str] | None = None


def _get_trusted_proxies() -> list[str]:
    """Cached access to trusted proxy networks."""
    global _TRUSTED_PROXY_CACHE
    if _TRUSTED_PROXY_CACHE is None:
        _TRUSTED_PROXY_CACHE = _load_trusted_proxies()
    return _TRUSTED_PROXY_CACHE


def _ip_is_trusted(
    ip_str: str,
    trusted_networks: list[str],
) -> bool:
    """Check if an IP address belongs to any trusted network."""
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False
    for entry in trusted_networks:
        try:
            net = ipaddress.ip_network(entry, strict=False)
            if addr in net:
                return True
        except ValueError:
            pass
    return False


def get_client_ip(request: Request) -> str:
    """Extract the real client IP from a request.

    When trusted proxies are configured in ``server.trusted_proxies``
    AND the direct TCP peer is one of them, the ``X-Forwarded-For``
    header is parsed (rightmost untrusted IP is the real client).

    Without trusted proxies (default), returns ``request.client.host``
    — the direct TCP peer — which is correct for direct deployments
    but will see only the proxy IP behind a reverse proxy.

    Configuration example (in llmwikify.json)::

        {
            "server": {
                "trusted_proxies": [
                    "127.0.0.1",
                    "10.0.0.0/8",
                    "172.16.0.0/12",
                    "192.168.0.0/16"
                ]
            }
        }
    """
    peer_ip = request.client.host if request.client else "unknown"

    trusted = _get_trusted_proxies()
    if not trusted:
        return peer_ip

    # Only parse X-Forwarded-For when the DIRECT peer is trusted
    if not _ip_is_trusted(peer_ip, trusted):
        return peer_ip

    forwarded = request.headers.get("X-Forwarded-For", "")
    if not forwarded:
        return peer_ip

    # X-Forwarded-For format: client, proxy1, proxy2
    # Walk from right to left; first non-trusted IP is the real client.
    ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    if not ips:
        return peer_ip

    for ip in reversed(ips):
        if not _ip_is_trusted(ip, trusted):
            return ip

    # All IPs are trusted — use the leftmost (original client)
    return ips[0]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter per IP address.

    Applied only to /api/agent/* routes. Returns 429 with a
    Retry-After header when the bucket is empty.

    Uses an LRU-style eviction: when the number of tracked IPs
    exceeds MAX_BUCKETS, the oldest entries are evicted to prevent
    memory exhaustion from spoofed/rotated IPs.

    Usage::

        app.add_middleware(RateLimitMiddleware)

    Disable by setting env var RATE_LIMIT_PER_MIN=0.
    """

    def __init__(
        self, app: ASGIApp, limit_per_min: int = RATE_LIMIT_PER_MIN
    ) -> None:
        super().__init__(app)
        self.limit_per_min = limit_per_min
        # Buckets: ip -> (tokens: float, last_refill: float)
        # Using OrderedDict for LRU-style eviction
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._max_buckets = MAX_BUCKETS

    def _get_or_create_bucket(self, client_ip: str) -> tuple[float, float]:
        """Get existing bucket or create new one with LRU eviction."""
        if client_ip in self._buckets:
            # Move to end (most recently used)
            self._buckets.move_to_end(client_ip)
            return self._buckets[client_ip]

        # Evict oldest entries if at capacity
        while len(self._buckets) >= self._max_buckets:
            self._buckets.popitem(last=False)

        # Create new bucket
        bucket = (float(self.limit_per_min), time.monotonic())
        self._buckets[client_ip] = bucket
        return bucket

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Only rate-limit agent API routes.
        path = request.url.path
        if not path.startswith("/api/agent"):
            return await call_next(request)

        if self.limit_per_min <= 0:
            return await call_next(request)

        client_ip = get_client_ip(request)
        now = time.monotonic()

        tokens, last_refill = self._get_or_create_bucket(client_ip)

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
      3. WebSocket handshake may pass ``?token=<api_key>`` (WS-only;
         HTTP ``_extract_token`` intentionally does NOT read query
         params — JWT-in-query leaks via referer logs)

    Decisions enforced:
      - 1   GET  (read)  + public_read=True  + no token    → 200
                  POST (write) + no token                    → 403
      - 4   scope based on HTTP method (GET=read, others=write)
      - 6   cookie secure=True on HTTPS, False on plain HTTP
                (P2-2; TLS termination at reverse proxy in production)
      - 7   wikis claim validated per-request against path
                /api/wiki/{wiki_id}/...
      - 12  local mode (loopback bind) → middleware is a
                pass-through: anyone on localhost is fully trusted,
                including POST/PUT/DELETE
    """

    def __init__(
        self,
        app: ASGIApp,
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

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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
                logger.debug(
                    "MW: %s %s → no token, GET+public_read → pass", request.method, path
                )
                return await call_next(request)
            logger.warning(
                "MW: %s %s → no token → deny (%s)",
                request.method,
                path,
                "401" if not self.public_read else "403",
            )
            return _deny_no_token(request.method, self.public_read)

        # Token present — verify (JWT first, then PAT fallback).
        # known_wikis feeds the PAT snapshot (P4a: PAT must not fall
        # into the legacy branch and grant non-admins full wiki access).
        claims = self._verify_token(token, self._known_wiki_ids(request))
        if claims is None:
            logger.warning(
                "MW: %s %s → token verify failed → 401", request.method, path
            )
            return _deny(401, "invalid_token", "Token is invalid or expired.")

        # P4a: one decision point — disabled / scope / admin / legacy /
        # live grants / snapshot (design §12.5). The no-token branch
        # above is unchanged this phase (public_read cleanup is P4b).
        from llmwikify.foundation.auth import authorize_request

        decision = authorize_request(
            claims,
            wiki_id=_wiki_id_from_path(path),
            need_write=request.method != "GET",
        )
        if not decision.allowed:
            logger.warning(
                "MW: %s %s → deny (%s): %s",
                request.method,
                path,
                decision.code,
                decision.detail,
            )
            return _deny(decision.status, decision.code, decision.detail)

        # Attach claims to request.state so downstream handlers can read.
        request.state.auth_claims = claims
        logger.debug(
            "MW: %s %s → pass (scope=%s, wikis=%s, wgrants=%s)",
            request.method,
            path,
            claims.scope,
            claims.wikis,
            claims.wgrants,
        )
        return await call_next(request)

    @staticmethod
    def _known_wiki_ids(request: Request) -> list[str]:
        """Registered wiki ids for PAT snapshot building (P4a)."""
        registry = getattr(request.app.state, "wiki_registry", None)
        if registry is None:
            return []
        try:
            return [w.wiki_id for w in registry.list_wikis()]
        except Exception:
            logger.debug("wiki enumeration failed", exc_info=True)
            return []

    def _extract_token(self, request: Request) -> str:
        """Read token from cookie (preferred) or Authorization header."""
        cookie_token = request.cookies.get("llmwikify_token")
        if cookie_token:
            return cookie_token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""

    def _verify_token(
        self, token: str, known_wikis: list[str] | None = None
    ) -> TokenClaims | None:
        """Try JWT decode first, then PAT lookup. Returns claims or None.

        P4a: the PAT branch builds a real snapshot via
        ``snapshot_for_user`` — signing ``wikis=["*"]`` with an empty
        ``wgrants`` would be misread as a legacy token and hand
        non-admins full wiki access.
        """
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
                logger.warning(
                    "failed to touch last_used_at for api_key %s",
                    api_key.id,
                    exc_info=True,
                )

            # Resolve user to build claims.
            user = UserRepository().get_by_id(api_key.user_id)
            if user is None:
                return None

            from llmwikify.foundation.auth import snapshot_for_user

            wikis, wgrants, computed = snapshot_for_user(
                user.id,
                known_wikis or [],
                is_admin=bool(user.is_first_admin),
            )
            # PAT scopes act as a ceiling: the tighter of the PAT scope
            # and the computed scope wins (a PAT cannot widen grants).
            scope = (
                "read"
                if (api_key.scopes == "read" or computed == "read")
                else "write"
            )
            return TokenClaims.new(
                sub=f"user:{user.id}",
                scope=scope,
                wikis=wikis,
                wgrants=wgrants,
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
    return _deny(
        403,
        "auth_required",
        f"{method} requires authentication; POST /auth/verify first.",
    )


def _wiki_id_from_path(path: str) -> str | None:
    """Extract the wiki_id from ``/api/wiki/{wiki_id}/...`` paths.

    Fixed routes like ``/api/wiki/status`` (4 segments) and
    ``/api/wiki/sink/...`` (non-wiki prefix) return ``None`` — they are
    not wiki-scoped, so only the global scope check applies.
    """
    if not path.startswith("/api/wiki/"):
        return None
    parts = path.split("/")
    if len(parts) < 5:
        return None
    wiki_id = parts[3]
    if wiki_id in frozenset({"sink"}):
        return None
    return wiki_id


def _check_wikis_claim(path: str, claims: TokenClaims) -> str | None:
    """Legacy wikis-claim check (kept for reference; P4a uses authorize)."""
    wiki_id = _wiki_id_from_path(path)
    if wiki_id is None:
        return None
    if "*" in claims.wikis:
        return None
    if wiki_id in claims.wikis:
        return None
    return (
        f"Token does not cover wiki {wiki_id!r}. "
        f"Allowed: {claims.wikis!r}. Re-run `llmwikify auth token` to refresh."
    )
