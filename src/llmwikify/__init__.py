"""
llmwikify - General-purpose LLM-Wiki CLI and Python Library

Based on Karpathy's LLM Wiki Principles:
- Persistent, LLM-maintained knowledge base
- Zero domain assumptions (pure tool design)
- Configuration-driven exclusion rules
- SQLite FTS5 full-text search
- Bidirectional reference tracking
"""

__version__ = "0.10.0"
__author__ = "Your Name"
__email__ = "your@email.com"
__license__ = "MIT"

from pathlib import Path

# Import main components
from .llmwikify import Wiki, WikiIndex, WikiCLI, MCPServer
from .llmwikify import ExtractedContent, Link, Issue, PageMeta

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


__all__ = [
    # Version
    "__version__",
    
    # Main classes
    "Wiki",
    "WikiIndex", 
    "WikiCLI",
    "MCPServer",
    
    # Data classes
    "ExtractedContent",
    "Link",
    "Issue",
    "PageMeta",
    
    # Convenience functions
    "create_wiki",
]
