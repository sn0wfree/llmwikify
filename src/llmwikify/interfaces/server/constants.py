"""Constants and enumerations for llmwikify server."""

from enum import Enum


class GraphMode(str, Enum):
    """Graph visualization display modes."""
    FULL = "full"
    FOCUSED = "focused"
    MINIMAL = "minimal"
    AUTO = "auto"


class TransportType(str, Enum):
    """MCP server transport modes."""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


# Authentication (Phase 2.5 — PAT-only)
# /auth/register and /auth/verify must be in EXCLUDED_AUTH_PATHS —
# otherwise the JWTAuthMiddleware would block the very routes that
# issue tokens. /auth/me and /auth/tokens require authentication.
# Both /auth/... and /api/auth/... variants are needed because the
# WebUI requests /api/auth/... (with the /api prefix).
EXCLUDED_AUTH_PATHS = {
    "/",
    "/mcp",
    "/api/health",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/register",
    "/auth/verify",
    "/api/auth/register",
    "/api/auth/verify",
}
EXCLUDED_AUTH_PREFIXES = {"/assets/"}

# Graph visualization defaults
DEFAULT_GRAPH_MODE = GraphMode.AUTO
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_LINT_LIMIT = 20

# Server defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
