"""Configuration management for llmwikify."""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import copy


# Default configuration (embedded for zero-dependency)
DEFAULT_CONFIG = {
    "directories": {
        "raw": "raw",
        "wiki": "wiki",
    },
    "files": {
        "index": "index.md",
        "log": "log.md",
        "config": ".wiki-config.yaml",
        "config_example": ".wiki-config.yaml.example",
    },
    "database": {
        "name": ".llmwikify.db",
    },
    "reference_index": {
        "name": "reference_index.json",
        "auto_export": True,
    },
    "orphan_detection": {
        "default_exclude_patterns": [
            r"^\d{4}-\d{2}-\d{2}$",  # Date: 2025-07-31
            r"^\d{4}-\d{2}$",        # Month: 2025-07
            r"^\d{4}-Q[1-4]$",       # Quarter: 2025-Q1
        ],
        "exclude_frontmatter": ["redirect_to"],
        "archive_directories": ["archive", "logs", "history"],
    },
    "performance": {
        "batch_size": 100,
        "cache_size": 64000,
    },
    "mcp": {
        "host": "127.0.0.1",
        "port": 8765,
        "transport": "stdio",
    },
}


def get_default_config() -> Dict[str, Any]:
    """Get a deep copy of the default configuration."""
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(wiki_root: Path, config_file: Optional[str] = None) -> Dict[str, Any]:
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
        config_path = wiki_root / DEFAULT_CONFIG["files"]["config"]
    
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
            # Config file has errors, use defaults
            print(f"Warning: Failed to load config from {config_path}: {e}")
    
    return config


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
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


def get_db_path(wiki_root: Path, config: Optional[Dict[str, Any]] = None) -> Path:
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


def get_directory(wiki_root: Path, dir_type: str, config: Optional[Dict[str, Any]] = None) -> Path:
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


def get_file_path(wiki_root: Path, file_type: str, config: Optional[Dict[str, Any]] = None) -> Path:
    """Get a file path based on configuration.
    
    Args:
        wiki_root: Wiki root directory
        file_type: Type of file ('index', 'log', etc.)
        config: Optional configuration dict
    
    Returns:
        Path to file
    """
    if config is None:
        config = get_default_config()
    
    file_name = config.get("files", {}).get(file_type, DEFAULT_CONFIG["files"][file_type])
    return wiki_root / file_name


def get_mcp_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get MCP server configuration.
    
    Args:
        config: Optional configuration dict
    
    Returns:
        MCP configuration dict with host, port, and transport
    """
    if config is None:
        config = get_default_config()
    
    mcp_config = DEFAULT_CONFIG["mcp"].copy()
    user_mcp = config.get("mcp", {})
    
    if user_mcp:
        mcp_config.update(user_mcp)
    
    return mcp_config
