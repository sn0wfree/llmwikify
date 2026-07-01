"""HTTP middleware components."""

from __future__ import annotations

import os
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from llmwikify.interfaces.server.constants import (
    EXCLUDED_AUTH_PATHS,
    EXCLUDED_AUTH_PREFIXES,
)

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


class AuthMiddleware(BaseHTTPMiddleware):
    """Simple API Key authentication middleware.

    Verifies requests using either:
    1. Header: Authorization: Bearer <token>
    2. Query param: ?token=<token> (fallback)

    Excludes:
    - Homepage /
    - MCP endpoint /mcp
    - Health check /api/health
    - API docs /docs, /redoc
    - Static assets /assets/
    """

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in EXCLUDED_AUTH_PATHS:
            return await call_next(request)
        for prefix in EXCLUDED_AUTH_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if not token:
            token = request.query_params.get("token", "")

        if token != self.api_key:
            return JSONResponse({"error": "Unauthorized", "status_code": 401}, status_code=401)

        return await call_next(request)
