"""Web search with multiple provider support.

Re-export of ``llmwikify.agent.backend.research.web_search``.
This module is a thin shim to avoid duplicating the WebSearch
implementation. The canonical home is
``llmwikify.agent.backend.research.web_search``.

This file will be replaced when the autoresearch framework is
rebuilt as a chat base + harness (see
docs/designs/code-reuse-modernization.md).
"""

from llmwikify.agent.backend.research.web_search import (  # noqa: F401
    DuckDuckGoProvider,
    FallbackSearchProvider,
    MiniMaxSearchProvider,
    SearchProvider,
    SearchResult,
    SearXNGProvider,
    TavilyProvider,
    WebSearch,
)

__all__ = [
    "DuckDuckGoProvider",
    "FallbackSearchProvider",
    "MiniMaxSearchProvider",
    "SearchProvider",
    "SearchResult",
    "SearXNGProvider",
    "TavilyProvider",
    "WebSearch",
]
