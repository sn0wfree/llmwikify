"""Configuration management for llmwikify."""

import copy
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default configuration (embedded for zero-dependency)
DEFAULT_CONFIG = {
    "directories": {
        "raw": "raw",
        "wiki": "wiki",
    },
    "database": {
        "name": ".llmwikify.db",
    },
    "reference_index": {
        "name": "reference_index.json",
        "auto_export": True,
    },
    "orphan_detection": {
        "default_exclude_patterns": [],
        "exclude_frontmatter": [],
        "archive_directories": [],
    },
    "performance": {
        "batch_size": 100,
    },
    "llm": {
        "enabled": False,
        "provider": "openai",
        "model": "gpt-4",
        "base_url": "http://localhost:11434",
        "api_key": "",
        "timeout": 120,
    },
    "mcp": {
        "name": None,
        "host": "127.0.0.1",
        "port": 8765,
        "transport": "stdio",
    },
    "web": {
        "port": 8766,
        "host": "127.0.0.1",
    },
    "prompts": {
        "custom_dir": None,
    },
    "search": {
        "backend": "fts5",  # "fts5" (default) or "qmd"
        "qmd": {
            "host": "127.0.0.1",
            "port": 8181,
            "auto_start": False,
        },
    },
}


def get_default_config() -> dict[str, Any]:
    """Get a deep copy of the default configuration."""
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(wiki_root: Path, config_file: str | None = None) -> dict[str, Any]:
    """Load configuration from .wiki-config.yaml, falling back to defaults.

    Args:
        wiki_root: Root directory of the wiki
        config_file: Optional custom config file path (relative to wiki_root)

    Returns:
        Merged configuration dict (user config overrides defaults)
    """
    config = get_default_config()

    # Determine config file path
    if config_file:
        config_path = wiki_root / config_file
    else:
        config_path = wiki_root / '.wiki-config.yaml'

    # Try to load user configuration
    if config_path.exists():
        try:
            import yaml

            user_config = yaml.safe_load(config_path.read_text())
            if user_config:
                # Deep merge user config into defaults
                config = _deep_merge(config, user_config)
        except ImportError:
            # PyYAML not installed, use defaults
            pass
        except Exception as e:
            logger.warning("Config file parse error, using defaults: %s", e)

    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base dictionary
        override: Dictionary with values to override

    Returns:
        Merged dictionary
    """
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def get_db_path(wiki_root: Path, config: dict[str, Any] | None = None) -> Path:
    """Get the database path based on configuration.

    Args:
        wiki_root: Wiki root directory
        config: Optional configuration dict

    Returns:
        Path to database file
    """
    if config is None:
        config = get_default_config()

    db_name = config.get("database", {}).get("name", DEFAULT_CONFIG["database"]["name"])
    return wiki_root / db_name


def get_directory(wiki_root: Path, dir_type: str, config: dict[str, Any] | None = None) -> Path:
    """Get a directory path based on configuration.

    Args:
        wiki_root: Wiki root directory
        dir_type: Type of directory ('raw' or 'wiki')
        config: Optional configuration dict

    Returns:
        Path to directory
    """
    if config is None:
        config = get_default_config()

    dir_name = config.get("directories", {}).get(dir_type, DEFAULT_CONFIG["directories"][dir_type])
    return wiki_root / dir_name


def get_mcp_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get MCP server configuration.

    Args:
        config: Optional configuration dict

    Returns:
        MCP configuration dict with host, port, and transport
    """
    if config is None:
        config = get_default_config()

    mcp_config: dict = DEFAULT_CONFIG["mcp"].copy()  # type: ignore[attr-defined]
    user_mcp = config.get("mcp", {})

    if user_mcp:
        mcp_config.update(user_mcp)

    return mcp_config


def get_search_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get search engine configuration.

    Args:
        config: Optional configuration dict

    Returns:
        Search configuration dict with backend and QMD settings
    """
    if config is None:
        config = get_default_config()

    search_config: dict = DEFAULT_CONFIG["search"].copy()  # type: ignore[attr-defined]
    user_search = config.get("search", {})

    if user_search:
        search_config.update(user_search)

    return search_config
