"""llmwikify unified server module."""

from typing import Any

from .core import WikiServer


def create_unified_server(wiki, agent=None, api_key=None, mcp_name=None) -> Any:
    """Backward compatible wrapper for WikiServer.

    DEPRECATED: Use WikiServer class directly instead.
    """
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

__all__ = ["WikiServer", "create_unified_server"]
