"""MCP protocol adapter for llmwikify."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from typing import Any, cast

from fastmcp import FastMCP

from llmwikify.kernel import Wiki
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

from .tools import register_multi_wiki_tools, register_wiki_tools

logger = logging.getLogger(__name__)


class MCPAdapter:
    """MCP protocol adapter - wraps wiki services as MCP tools.

    Provides a clean interface for running MCP in different modes:
    - stdio: for integration with Claude Desktop, Cursor, etc.
    - http/sse: for network access and service discovery
    - asgi_app: for embedding in unified server

    Supports both single-wiki and multi-wiki modes.
    """

    def __init__(
        self,
        wiki: Wiki | WikiRegistry,
        name: str | None = None,
        config: dict[str, Any] | None = None,
    ):
        # Support both single Wiki and WikiRegistry
        if isinstance(wiki, WikiRegistry):
            self.registry: WikiRegistry | None = wiki
            self.wiki = wiki.get_default_wiki() if wiki.get_default_wiki_id() else None
            self.name = (
                name or (config.get("name") if config else None) or "llmwikify-multi"
            )
        else:
            self.registry = None
            self.wiki = wiki
            self.name = (
                name or (config.get("name") if config else None) or wiki.root.name
            )

        self._mcp = FastMCP(self.name)

        # Register tools based on mode. In registry mode the 20 core
        # tools are registered first with dynamic default-wiki
        # resolution, then the two same-named multi-wiki variants
        # (wiki_status / wiki_search, which take wiki_id) replace them —
        # giving the 26 unique names the v0.31 design specifies, without
        # FastMCP's "Component already exists" warning.
        # See docs/designs/multi-wiki-mcp-reconnect.md.
        if self.registry:
            register_wiki_tools(self._mcp, self.wiki, registry=self.registry)
            for _name in ("wiki_status", "wiki_search"):
                self._remove_tool(_name)
            register_multi_wiki_tools(self._mcp, self.registry)
        elif self.wiki:
            register_wiki_tools(self._mcp, self.wiki)

    def _remove_tool(self, name: str) -> None:
        """Drop a same-named tool before the multi-wiki variant re-adds it.

        fastmcp >=3.2 deprecates ``FastMCP.remove_tool`` in favour of
        ``local_provider.remove_tool``; the pyproject range allows
        ``>=3.0,<3.3``, so prefer the new path when present.
        """
        provider = getattr(self._mcp, "local_provider", None)
        if provider is not None and hasattr(provider, "remove_tool"):
            provider.remove_tool(name)
        else:
            self._mcp.remove_tool(name)

    @property
    def asgi_app(self) -> Any:
        """Get MCP ASGI app for mounting in FastAPI/Starlette.

        Uses ``path="/"`` because the unified server mounts this app at
        ``/mcp``. FastMCP's default ``/mcp`` would become ``/mcp/mcp``.
        """
        return self._mcp.http_app(path="/")

    async def run_stdio(self) -> None:
        """Run MCP server in stdio mode (for desktop integration)."""
        await cast("Awaitable[None]", self._mcp.run(transport="stdio"))

    async def run_http(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run MCP server in HTTP mode (for network access)."""
        await cast(
            "Awaitable[None]", self._mcp.run(transport="http", host=host, port=port)
        )

    async def run_sse(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run MCP server in SSE mode."""
        await cast(
            "Awaitable[None]", self._mcp.run(transport="sse", host=host, port=port)
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool programmatically (for MCP protocol use only)."""
        result = await self._mcp.call_tool(name, arguments)
        return self._parse_result(result)

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
