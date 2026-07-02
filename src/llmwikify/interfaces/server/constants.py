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
# Auth routes are registered under /api/auth (consistent with other routers).
# /auth/register and /auth/verify are excluded for CLI/curl direct access.
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
    "/api/auth/logout",
}
EXCLUDED_AUTH_PREFIXES = {"/assets/"}

# Graph visualization defaults
DEFAULT_GRAPH_MODE = GraphMode.AUTO
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_LINT_LIMIT = 20

# Server defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
