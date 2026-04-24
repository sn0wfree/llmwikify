"""MCP protocol adapter for llmwikify."""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
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
    - sync/async tool calls: for REST API handlers
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
        """Call an MCP tool programmatically (async)."""
        result = await self._mcp.call_tool(name, arguments)
        return self._parse_result(result)

    def call_tool_sync(self, name: str, **kwargs) -> Any:
        """Call an MCP tool programmatically (sync wrapper for REST API)."""
        return asyncio.run(self.call_tool(name, kwargs))

    def _parse_result(self, result: Any) -> Any:
        """Parse FastMCP result content to native Python types."""
        if hasattr(result, "content"):
            content = result.content
            if isinstance(content, list) and len(content) > 0:
                item = content[0]
                if hasattr(item, "text"):
                    text = item.text
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        return text
                return item
            return content
        return result

    # Typed shortcut methods for REST API handlers
    @lru_cache(maxsize=32)
    def wiki_status(self) -> dict[str, Any]:
        """Get wiki status (cached for performance)."""
        return self.call_tool_sync("wiki_status")

    def wiki_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search wiki pages."""
        return self.call_tool_sync("wiki_search", query=query, limit=limit)

    def wiki_lint(self, mode: str = "check", limit: int = 10, force: bool = False) -> dict[str, Any]:
        """Lint wiki for issues."""
        return self.call_tool_sync("wiki_lint", mode=mode, limit=limit, force=force)

    def wiki_recommend(self) -> dict[str, Any]:
        """Get wiki recommendations."""
        return self.call_tool_sync("wiki_recommend")

    def wiki_suggest_synthesis(self, source_name: str | None = None) -> dict[str, Any]:
        """Get synthesis suggestions."""
        kwargs = {"source_name": source_name} if source_name else {}
        return self.call_tool_sync("wiki_suggest_synthesis", **kwargs)

    def wiki_graph_analyze(self) -> dict[str, Any]:
        """Analyze knowledge graph."""
        return self.call_tool_sync("wiki_graph_analyze")
