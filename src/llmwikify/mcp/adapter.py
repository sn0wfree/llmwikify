"""MCP protocol adapter for llmwikify."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from llmwikify.core import Wiki

from .tools import register_wiki_tools


logger = logging.getLogger(__name__)


class MCPAdapter:
    """MCP protocol adapter - wraps wiki services as MCP tools.

    Provides a clean interface for running MCP in different modes:
    - stdio: for integration with Claude Desktop, Cursor, etc.
    - http/sse: for network access and service discovery
    - asgi_app: for embedding in unified server
    """

    def __init__(self, wiki: Wiki, name: str | None = None, config: dict[str, Any] | None = None):
        self.wiki = wiki
        self.name = name or (config.get("name") if config else None) or wiki.root.name
        self._mcp = FastMCP(self.name)
        register_wiki_tools(self._mcp, wiki)

    @property
    def asgi_app(self):
        """Get MCP ASGI app for mounting in FastAPI/Starlette."""
        return self._mcp.http_app()

    async def run_stdio(self) -> None:
        """Run MCP server in stdio mode (for desktop integration)."""
        await self._mcp.run(transport="stdio")

    async def run_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run MCP server in HTTP mode (for network access)."""
        await self._mcp.run(transport="http", host=host, port=port)

    async def run_sse(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run MCP server in SSE mode."""
        await self._mcp.run(transport="sse", host=host, port=port)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool programmatically (for testing)."""
        return await self._mcp.call_tool(name, arguments)
