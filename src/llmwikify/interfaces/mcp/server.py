"""MCP server shim — thin delegations to MCPAdapter / WikiServer.

Stable shim maintained for backward compat with callers that import
from ``llmwikify.mcp.server``. All 3 functions are 1-line delegations
to the canonical implementations:
  - create_mcp_server()    → MCPAdapter(wiki)._mcp
  - serve_mcp()            → MCPAdapter(wiki).run_<transport>()
  - create_unified_server() → WikiServer(wiki).app
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from llmwikify.kernel import Wiki


def create_mcp_server(
    wiki: Wiki,
    name: str | None = None,
    config: dict[str, Any] | None = None,
) -> FastMCP:
    """Create FastMCP server. → ``MCPAdapter(wiki)._mcp``."""
    from .adapter import MCPAdapter
    return MCPAdapter(wiki, name=name, config=config)._mcp


def serve_mcp(
    wiki: Wiki,
    name: str | None = None,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    config: dict[str, Any] | None = None,
) -> None:
    """Start MCP server. → ``MCPAdapter(wiki).run_<transport>()``."""
    from .adapter import MCPAdapter
    adapter = MCPAdapter(wiki, name=name, config=config)
    if transport == "stdio":
        asyncio.run(adapter.run_stdio())
    elif transport == "http":
        asyncio.run(adapter.run_http(host, port))
    elif transport == "sse":
        asyncio.run(adapter.run_sse(host, port))
    else:
        raise ValueError(
            f"Unsupported transport: {transport}. "
            "Use 'stdio', 'http', or 'sse'."
        )


def create_unified_server(
    wiki: Wiki,
    agent: Any | None = None,  # noqa: ARG001 - Kept for backward compat
    api_key: str | None = None,
    mcp_name: str | None = None,
) -> Any:
    """Create FastAPI app. → ``WikiServer(wiki).app``."""
    from llmwikify.interfaces.server import WikiServer
    server = WikiServer(
        wiki,
        api_key=api_key,
        mcp_name=mcp_name,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
    )
    return server.app

