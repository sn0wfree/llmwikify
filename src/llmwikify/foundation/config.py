"""Configuration management for llmwikify."""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

from .params import param_default, section_defaults

logger = logging.getLogger(__name__)

# Sentinel for "key not present in this scope" — None is a legal value.
_MISSING = object()


def _lookup_path(container: Any, dotted: str) -> Any:
    """Walk a dotted path through nested dicts.

    Returns ``_MISSING`` when any step is absent.
    """
    cursor = container
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return _MISSING
        cursor = cursor[part]
    return cursor

# Sections exposed by the embedded default config. The *values* come from
# the parameter registry (foundation/params.py) — they are never written
# twice. The list only fixes which sections are part of the embedded
# default document.
_DEFAULT_CONFIG_SECTIONS = (
    "directories",
    "database",
    "reference_index",
    "orphan_detection",
    "performance",
    "llm",
    "mcp",
    "web",
    "prompts",
    "search",
    "wikis",
)

DEFAULT_CONFIG: dict[str, Any] = {
    section: section_defaults(section) for section in _DEFAULT_CONFIG_SECTIONS
}

# Template default config path (package-relative)
_DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "templates" / "llmwikify.default.json"


def global_config_home() -> Path:
    """Resolve the ``.llmwikify`` directory holding the global config.

    ``$LLMWIKIFY_HOME`` wins when set; otherwise the user's home. The
    env var is the only override that works on every platform —
    ``os.path.expanduser("~")`` ignores ``$HOME`` on Windows (it resolves
    ``USERPROFILE``) and ``Path.home()`` ignores it on Linux (it consults
    ``/etc/passwd``). Computed at call time so tests can redirect it.
    """
    home = os.environ.get("LLMWIKIFY_HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / ".llmwikify"


# ─── Config Singleton ────────────────────────────────────────────


class Config:
    """Global configuration singleton.

    Loads and caches ~/.llmwikify/llmwikify.json with section-based access.
    Respects $LLMWIKIFY_HOME environment variable.

    Usage::

        from llmwikify.foundation.config import config

        llm_cfg = config.get("llm")
        research_cfg = config.get("research")
        full_cfg = config.get()
        wiki_cfg = config.get_wiki_config("/path/to/wiki")
    """

    _instance: Config | None = None
    # Declared at class level so __init__ can read it before the first
    # __new__ assignment is visible to type checkers.
    _initialized: bool = False

    def __new__(cls) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._home = global_config_home()
        self._path = self._home / "llmwikify.json"
        self._cache: dict[str, Any] | None = None
        self._wiki_cache: dict[str, dict[str, Any]] = {}
        self._template_cache: dict[str, Any] | None = None

    @property
    def home(self) -> Path:
        """~/.llmwikify directory."""
        return self._home

    @property
    def path(self) -> Path:
        """~/.llmwikify/llmwikify.json path."""
        return self._path

    def get(self, section: str | None = None, default: Any = None) -> Any:
        """Get config section or full config.

        Args:
            section: Section name (e.g., 'llm', 'research'). None for full config.
            default: Default value if section doesn't exist.

        Returns:
            Requested section or full config dict.
        """
        if self._cache is None:
            from llmwikify.foundation.io import read_json

            self._cache = read_json(self._path, {})
        if section is None:
            return self._cache
        return self._cache.get(section, default if default is not None else {})

    def get_wiki_config(self, wiki_root: Path | str) -> dict[str, Any]:
        """Get per-wiki config from .wiki-config.yaml.

        Args:
            wiki_root: Wiki root directory.

        Returns:
            Wiki config dict, or {} if not found.
        """
        wiki_root = Path(wiki_root)
        cache_key = str(wiki_root)
        if cache_key not in self._wiki_cache:
            from llmwikify.foundation.io import read_yaml

            self._wiki_cache[cache_key] = read_yaml(wiki_root / ".wiki-config.yaml", {})
        return self._wiki_cache[cache_key]

    def get_default(self, section: str) -> dict[str, Any]:
        """Get default config section from template.

        Args:
            section: Section name (e.g., 'llm', 'research').

        Returns:
            Default section dict from template, or empty dict.
        """
        if self._template_cache is None:
            from llmwikify.foundation.io import read_json

            self._template_cache = read_json(_DEFAULT_TEMPLATE_PATH, {})
        return copy.deepcopy(self._template_cache.get(section, {}))

    def get_param(
        self,
        key: str,
        *,
        wiki_root: Path | str | None = None,
    ) -> Any:
        """Resolve one parameter through the documented scopes.

        per-wiki ``.wiki-config.yaml``  >  global ``~/.llmwikify/llmwikify.json``
        >  the registry default (``foundation.params``).

        Args:
            key: Dotted parameter key, e.g. ``"llm.timeout"`` or
                ``"wikis.discovery.scan_depth"``. A bare section name
                (``"llm"``) returns the whole section as a dict.
            wiki_root: When given, the per-wiki scope is consulted first.

        Returns:
            The resolved value, or the registry default when nothing
            overrides it. Unknown keys resolve to ``None`` rather than
            raising — use :func:`llmwikify.foundation.params.param_spec`
            when a missing declaration must be loud.
        """
        section, _, rest = key.partition(".")
        if not rest:
            return copy.deepcopy(section_defaults(section))

        if wiki_root is not None:
            found = _lookup_path(self.get_wiki_config(wiki_root), key)
            if found is not _MISSING:
                return found

        global_cfg = self.get()
        found = _lookup_path(global_cfg.get(section, {}), rest)
        if found is not _MISSING:
            return found

        return param_default(key)

    def save(self, data: dict[str, Any], section: str | None = None) -> None:
        """Save config to the global config file.

        Args:
            data: Config data to save.
            section: If provided, save as {"section": data}. Otherwise save as-is.
        """
        self.ensure_dir()
        from llmwikify.foundation.io import write_json

        if section is not None:
            # Load existing, merge section, save
            existing = self.get()
            existing[section] = data
            write_json(self._path, existing)
        else:
            write_json(self._path, data)
        self._cache = None  # Invalidate cache

    def reload(self) -> None:
        """Clear cache, forcing next get() to re-read from disk."""
        self._cache = None
        self._wiki_cache.clear()
        self._template_cache = None

    def ensure_dir(self) -> None:
        """Ensure ~/.llmwikify directory exists."""
        self._home.mkdir(parents=True, exist_ok=True)


# Module-level singleton instance
config = Config()


# ─── Backward-compatible functions ───────────────────────────────


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
    cfg = get_default_config()

    # Determine config file path
    if config_file:
        config_path = wiki_root / config_file
    else:
        config_path = wiki_root / ".wiki-config.yaml"

    # Try to load user configuration
    if config_path.exists():
        try:
            import yaml

            user_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if user_config:
                # Deep merge user config into defaults
                from llmwikify.foundation.utils import deep_merge

                cfg = deep_merge(cfg, user_config)
        except ImportError:
            # PyYAML not installed, use defaults
            pass
        except Exception as e:
            logger.warning("Config file parse error, using defaults: %s", e)

    return cfg


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.

    .. deprecated:: Use ``foundation.utils.deep_merge`` instead.
    """
    from llmwikify.foundation.utils import deep_merge

    return deep_merge(base, override)


def get_db_path(wiki_root: Path, cfg: dict[str, Any] | None = None) -> Path:
    """Get the database path based on configuration.

    Args:
        wiki_root: Wiki root directory
        cfg: Optional configuration dict

    Returns:
        Path to database file
    """
    if cfg is None:
        cfg = get_default_config()

    db_name: str = cfg.get("database", {}).get(
        "name", DEFAULT_CONFIG["database"]["name"]
    )
    return wiki_root / db_name


def get_directory(
    wiki_root: Path, dir_type: str, cfg: dict[str, Any] | None = None
) -> Path:
    """Get a directory path based on configuration.

    Args:
        wiki_root: Wiki root directory
        dir_type: Type of directory ('raw' or 'wiki')
        cfg: Optional configuration dict

    Returns:
        Path to directory
    """
    if cfg is None:
        cfg = get_default_config()

    dir_name: str = cfg.get("directories", {}).get(
        dir_type, DEFAULT_CONFIG["directories"][dir_type]
    )
    return wiki_root / dir_name


def _section_config(
    section: str,
    cfg: dict[str, Any] | None = None,
    *,
    deep: bool = False,
) -> dict[str, Any]:
    """Overlay the user's ``cfg[section]`` on ``DEFAULT_CONFIG[section]``.

    Args:
        section: Key in both ``DEFAULT_CONFIG`` and the user config.
        cfg: Optional configuration dict; defaults to ``get_default_config()``.
        deep: Merge nested dicts instead of replacing top-level keys
            (``wikis`` nests ``local``/``remote``/``discovery``).

    Returns:
        A merged copy — never a view onto ``DEFAULT_CONFIG``.
    """
    if cfg is None:
        cfg = get_default_config()

    merged: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG[section])
    user_cfg = cfg.get(section, {})
    if user_cfg:
        if deep:
            from llmwikify.foundation.utils import deep_merge

            merged = deep_merge(merged, user_cfg)
        else:
            merged.update(user_cfg)
    return merged


def get_mcp_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get MCP server configuration.

    Args:
        cfg: Optional configuration dict

    Returns:
        MCP configuration dict with host, port, and transport
    """
    return _section_config("mcp", cfg)


def get_search_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get search engine configuration.

    Args:
        cfg: Optional configuration dict

    Returns:
        Search configuration dict with backend and QMD settings
    """
    return _section_config("search", cfg)


def get_wikis_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get multi-wiki configuration.

    Args:
        cfg: Optional configuration dict

    Returns:
        Wikis configuration dict with default, local, remote, and discovery settings
    """
    return _section_config("wikis", cfg, deep=True)


def expand_env_vars(value: str) -> str:
    """Expand environment variables in string values.

    Supports ${VAR_NAME} syntax.

    Args:
        value: String value potentially containing env var references

    Returns:
        Expanded string
    """
    import re

    def replace_env(match: re.Match) -> str:
        var_name = match.group(1)
        # match.group() is Any in typeshed; pin the fallback to str so
        # os.environ.get returns str.
        fallback: str = match.group(0)
        return os.environ.get(var_name, fallback)

    return re.sub(r"\$\{(\w+)\}", replace_env, value)


__all__ = [
    "Config",
    "config",
    "DEFAULT_CONFIG",
    "get_default_config",
    "load_config",
    "get_db_path",
    "get_directory",
    "get_mcp_config",
    "get_search_config",
    "get_wikis_config",
    "expand_env_vars",
]
