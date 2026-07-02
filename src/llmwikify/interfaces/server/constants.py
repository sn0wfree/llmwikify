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


# Authentication (Phase 2a)
# /auth/login must be in EXCLUDED_AUTH_PATHS — otherwise the
# JWTAuthMiddleware would block the very route that issues tokens.
# /auth/me is NOT excluded; it requires an existing cookie/token.
EXCLUDED_AUTH_PATHS = {
    "/",
    "/mcp",
    "/api/health",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/login",
}
EXCLUDED_AUTH_PREFIXES = {"/assets/"}

# Graph visualization defaults
DEFAULT_GRAPH_MODE = GraphMode.AUTO
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_LINT_LIMIT = 20

# Server defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
