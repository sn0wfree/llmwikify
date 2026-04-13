"""
llmwikify - General-purpose LLM-Wiki CLI and Python Library

Based on Karpathy's LLM Wiki Principles:
- Persistent, LLM-maintained knowledge base
- Zero domain assumptions (pure tool design)
- Configuration-driven exclusion rules
- SQLite FTS5 full-text search
- Bidirectional reference tracking
"""

__version__ = "0.25.0"
__author__ = "sn0wfree"
__email__ = "linlu1234567@sina.com"
__license__ = "MIT"

from pathlib import Path
from typing import Optional, Dict

# Import main components from modules
from .core import Wiki, WikiIndex
from .cli import WikiCLI
from .mcp import create_mcp_server, serve_mcp
from .extractors import ExtractedContent, Link
from .config import (
    load_config,
    get_default_config,
    get_mcp_config,
)

# Convenience functions
def create_wiki(path: str | Path, config: Optional[Dict] = None) -> Wiki:
    """Create or open a wiki at the given path.
    
    Args:
        path: Path to wiki root directory
        config: Optional configuration dict
        
    Returns:
        Wiki instance
    """
    return Wiki(Path(path), config=config)


__all__ = [
    # Version
    "__version__",
    
    # Main classes
    "Wiki",
    "WikiIndex", 
    "WikiCLI",
    "create_mcp_server",
    "serve_mcp",
    
    # Data classes
    "ExtractedContent",
    "Link",
    
    # Configuration
    "load_config",
    "get_default_config",
    "get_mcp_config",
    
    # Convenience functions
    "create_wiki",
]
