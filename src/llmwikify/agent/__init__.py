"""llmwikify Agent - Autonomous wiki maintenance layer.

⚠️ DEPRECATED ⚠️

This agent module has been moved to an independent project.
The llmwikify core now focuses on being a great knowledge base tool,
with full MCP protocol support for external AI agents.

If you need agent capabilities:
  1. Use any external AI agent (Claude, Cursor, OpenCode, etc.)
  2. Connect via llmwikify MCP server: `llmwikify mcp`

This module is kept for backward compatibility only and will be
removed in a future version.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "llmwikify.agent module is DEPRECATED and moved to an independent project. "
    "Use external AI agents with MCP protocol instead: `llmwikify mcp`",
    DeprecationWarning,
    stacklevel=2,
)

from .wiki_agent import WikiAgent

__all__ = ["WikiAgent"]
