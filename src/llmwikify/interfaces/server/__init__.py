"""llmwikify unified server module."""

from typing import Any

from .core import WikiServer


def create_unified_server(
    wiki,
    agent=None,  # noqa: ARG001 - kept for backward compat
    api_key=None,
    mcp_name=None,
) -> Any:
    """Backward compatible wrapper for WikiServer.

    DEPRECATED: Use WikiServer class directly instead.
    """
    # 2026-10-14 fix (Bug 4): WikiServer has no `agent` parameter — the
    # previous call passed it and raised TypeError on every invocation
    # (mirrors the correct wrapper in interfaces/mcp/server.py).
    server = WikiServer(
        wiki,
        api_key=api_key,
        mcp_name=mcp_name,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
    )
    return server.app


__all__ = ["WikiServer", "create_unified_server"]
