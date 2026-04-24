"""MCP server for llmwikify using FastMCP.

DEPRECATED: Use llmwikify.server.WikiServer for new code.
This module is maintained for backward compatibility only.
Please migrate to the new unified server architecture.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from fastmcp import FastMCP

from llmwikify.core import Wiki
from llmwikify.server import WikiServer

from .tools import register_wiki_tools


warnings.warn(
    "llmwikify.mcp.server is deprecated. Use llmwikify.server.WikiServer instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


def create_mcp_server(wiki: Wiki, name: str | None = None, config: dict[str, Any] | None = None) -> FastMCP:
    """Create a FastMCP server with all wiki tools registered.

    DEPRECATED: Use MCPAdapter directly from llmwikify.mcp.adapter.

    Args:
        wiki: Wiki instance to operate on
        name: Optional server name (defaults to directory name)
        config: Optional MCP configuration dict

    Returns:
        Configured FastMCP server instance
    """
    service_name = name
    if not service_name and config:
        service_name = config.get("name")
    if not service_name:
        service_name = wiki.root.name

    mcp = FastMCP(service_name)

    default_config = {"name": None, "host": "127.0.0.1", "port": 8765, "transport": "stdio"}
    server_config = default_config.copy()
    if config:
        server_config.update(config)
    else:
        user_mcp = wiki.config.get("mcp", {})
        if user_mcp:
            server_config.update(user_mcp)
    mcp._server_config = server_config  # type: ignore[attr-defined]

    # Use the single source of truth for tool registration
    register_wiki_tools(mcp, wiki)

    return mcp


def serve_mcp(
    wiki: Wiki,
    name: str | None = None,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    config: dict[str, Any] | None = None,
) -> None:
    """Start MCP server.

    DEPRECATED: Use MCPAdapter.run_stdio() / run_http().

    Args:
        wiki: Wiki instance
        name: Optional service name
        transport: 'stdio', 'http', or 'sse'
        host: Bind address for http/sse modes
        port: Port number for http/sse modes
        config: Optional additional config
    """
    from .adapter import MCPAdapter
    import asyncio

    logger.info(f"Starting MCP server in {transport} mode on {host}:{port}")

    adapter = MCPAdapter(wiki, name=name, config=config)

    if transport == "stdio":
        asyncio.run(adapter.run_stdio())
    elif transport == "http":
        asyncio.run(adapter.run_http(host, port))
    elif transport == "sse":
        asyncio.run(adapter.run_sse(host, port))
    else:
        raise ValueError(f"Unsupported transport: {transport}. Use 'stdio', 'http', or 'sse'.")


def create_unified_server(
    wiki: Wiki,
    agent: Any | None = None,
    api_key: str | None = None,
    mcp_name: str | None = None,
) -> Any:
    """Create a unified FastAPI server with MCP, REST API, and WebUI.

    DEPRECATED: Use llmwikify.server.WikiServer directly.

    Args:
        wiki: Wiki instance
        agent: Optional WikiAgent instance
        api_key: Optional API key for authentication
        mcp_name: Optional MCP server name

    Returns:
        FastAPI application
    """
    warnings.warn(
        "create_unified_server() is deprecated. Use WikiServer class instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    server = WikiServer(
        wiki,
        agent=agent,
        api_key=api_key,
        mcp_name=mcp_name,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
    )
    return server.app
