"""llmwikify unified server module."""

from .core import WikiServer

# Backward compatibility - create_unified_server now uses new core
def create_unified_server(wiki, agent=None, api_key=None, mcp_name=None):
    """Backward compatible wrapper for WikiServer."""
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
