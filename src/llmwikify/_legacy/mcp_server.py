"""Backward-compat shim for ``llmwikify.mcp.server``.

Per Batch B2 of the 4-layer refactor, ``mcp/`` moved to
``interfaces/mcp/``. External code that imported
``create_mcp_server``, ``serve_mcp`` or ``create_unified_server``
from ``llmwikify.mcp.server`` should switch to
``llmwikify.interfaces.mcp``.

This module preserves the old entry point until v0.33.0 and
emits a ``DeprecationWarning`` to make the migration obvious.
"""
from __future__ import annotations

import warnings

from llmwikify.interfaces.mcp.server import (  # noqa: F401
    create_mcp_server,
    create_unified_server,
    serve_mcp,
)

warnings.warn(
    "llmwikify.mcp.server is moved to llmwikify.interfaces.mcp in the "
    "4-layer refactor. Update your imports to llmwikify.interfaces.mcp "
    "(or the more specific llmwikify.interfaces.mcp.server for the "
    "create_mcp_server / serve_mcp / create_unified_server functions). "
    "This shim will be removed in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["create_mcp_server", "serve_mcp", "create_unified_server"]
