"""
llmwikify - General-purpose LLM-Wiki CLI and Python Library

Based on Karpathy's LLM Wiki Principles:
- Persistent, LLM-maintained knowledge base
- Zero domain assumptions (pure tool design)
- Configuration-driven exclusion rules
- SQLite FTS5 full-text search
- Bidirectional reference tracking
"""

__version__ = "0.38.0"
__author__ = "sn0wfree"
__email__ = "linlu1234567@sina.com"
__license__ = "MIT"

from pathlib import Path

from .interfaces.cli import WikiCLI
from .foundation.config import (
    get_default_config,
    get_mcp_config,
    get_wikis_config,
    load_config,
)

# Import main components from modules
from .kernel import Wiki, WikiIndex
from .kernel.multi_wiki.remote import RemoteWiki
from .kernel.multi_wiki.discovery import WikiDiscovery
from .kernel.multi_wiki.instance import WikiInstance, WikiStatus, WikiType
from .kernel.multi_wiki.registry import WikiRegistry
from .foundation.extractors import ExtractedContent, Link
from .interfaces.mcp import create_mcp_server, serve_mcp


# Convenience functions
def create_wiki(path: str | Path, config: dict | None = None) -> Wiki:
    """Create or open a wiki at the given path.

    Args:
        path: Path to wiki root directory
        config: Optional configuration dict

    Returns:
        Wiki instance
    """
    return Wiki(Path(path), config=config)


def create_multi_wiki(config: dict | None = None, wiki_root: str | Path | None = None) -> WikiRegistry:
    """Create a WikiRegistry with multiple wikis.

    Args:
        config: Optional configuration dict (or None to load from wiki_root)
        wiki_root: Optional wiki root path for config loading

    Returns:
        WikiRegistry instance
    """
    if config is None:
        if wiki_root is None:
            wiki_root = Path.cwd()
        config = load_config(Path(wiki_root))

    registry = WikiRegistry(config)
    registry.initialize()
    return registry


__all__ = [
    # Version
    "__version__",

    # Main classes
    "Wiki",
    "WikiIndex",
    "WikiCLI",
    "WikiRegistry",
    "WikiInstance",
    "WikiType",
    "WikiStatus",
    "RemoteWiki",
    "WikiDiscovery",
    "create_mcp_server",
    "serve_mcp",

    # Data classes
    "ExtractedContent",
    "Link",

    # Configuration
    "load_config",
    "get_default_config",
    "get_mcp_config",
    "get_wikis_config",

    # Convenience functions
    "create_wiki",
    "create_multi_wiki",
]
