"""HTTP middleware components."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from llmwikify.server.constants import EXCLUDED_AUTH_PATHS, EXCLUDED_AUTH_PREFIXES


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
