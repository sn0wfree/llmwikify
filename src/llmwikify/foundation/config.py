"""Configuration management for llmwikify."""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .params import (
    PARAMS,
    AppsParams,
    FoundationParams,
    InterfacesParams,
    KernelParams,
    Param,
    aliases_of,
    canonical_key,
    param_default,
    section_defaults,
)

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
        self._cache: dict[str, Any] | None = None
        self._wiki_cache: dict[str, dict[str, Any]] = {}
        self._template_cache: dict[str, Any] | None = None

    @property
    def home(self) -> Path:
        """``~/.llmwikify`` directory.

        Resolved at **call time**, not cached at import: ``Config`` is a
        singleton created when this module is first imported, so caching
        the path there would freeze ``$LLMWIKIFY_HOME`` before a test (or
        any later re-pointing) can take effect — the same import-time
        capture bug as ``doctor_cmd.CONFIG_PATH`` and ``_keyring._SECRET_FILE``.
        """
        return global_config_home()

    @property
    def path(self) -> Path:
        """``~/.llmwikify/llmwikify.json`` path."""
        return self.home / "llmwikify.json"

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

            self._cache = read_json(self.path, {})
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
            write_json(self.path, existing)
        else:
            write_json(self.path, data)
        self._cache = None  # Invalidate cache

    def reload(self) -> None:
        """Clear cache, forcing next get() to re-read from disk."""
        self._cache = None
        self._wiki_cache.clear()
        self._template_cache = None

    def ensure_dir(self) -> None:
        """Ensure ~/.llmwikify directory exists."""
        self.home.mkdir(parents=True, exist_ok=True)


def _coerce(raw: str, target: type | None) -> Any:
    """Convert an env-var string to the parameter's declared type."""
    if target is None or target is str:
        return raw
    if target is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        return target(raw)
    except (TypeError, ValueError):
        return raw


class ParamRegistry:
    """Resolves every declared parameter through the documented scopes.

    Scopes, highest first::

        env  >  per-wiki .wiki-config.yaml  >  global llmwikify.json  >  registry default

    One instance per ``wiki_root`` (see :func:`registry_for`). Resolves
    lazily and caches until :meth:`reload`; :meth:`reload` re-resolves,
    returns the changed keys, and notifies :meth:`on_change` listeners —
    the push/pull split from S2 (pull for cheap values, callback only for
    expensive derived objects such as an LLM client).
    """

    def __init__(
        self,
        *,
        wiki_root: Path | str | None = None,
        config: Config | None = None,
    ) -> None:
        self._wiki_root = Path(wiki_root) if wiki_root is not None else None
        self._config = config if config is not None else Config()
        self._listeners: list[Callable[[set[str]], None]] = []
        self._cache: dict[str, Any] | None = None
        self._sources: dict[str, str] | None = None

    # ── Resolution ───────────────────────────────────────────────

    def resolve(self) -> dict[str, Any]:
        """Resolve every registered key. Cached until :meth:`reload`."""
        if self._cache is None:
            cache: dict[str, Any] = {}
            sources: dict[str, str] = {}
            for key in PARAMS:
                value, source = self._resolve_one(key)
                cache[key] = value
                sources[key] = source
            self._cache = cache
            self._sources = sources
        return self._cache

    def _resolve_one(self, key: str) -> tuple[Any, str]:
        # D5 (iii): every key in an alias family resolves through its
        # canonical, so one concept has one value. The canonical's own
        # scopes win; a deprecated alias's user setting is consulted
        # only when the canonical has none.
        canonical = canonical_key(key)
        spec: Param | None = PARAMS.get(canonical)
        default = spec.default if spec is not None else None

        # 1. env on the canonical (deployment override)
        if spec is not None and spec.env:
            raw = os.environ.get(spec.env)
            if raw is not None and raw != "":
                return _coerce(raw, spec.type), "env"

        section, _, rest = canonical.partition(".")
        if not rest:
            # A bare section name: the whole section, registry defaults.
            return section_defaults(section), "registry"

        wiki_cfg: dict[str, Any] | None = None
        if self._wiki_root is not None:
            wiki_cfg = self._config.get_wiki_config(self._wiki_root)

        # 2. canonical's own per-wiki / global setting
        if wiki_cfg is not None:
            found = _lookup_path(wiki_cfg, canonical)
            if found is not _MISSING:
                return found, "wiki"
        found = _lookup_path(self._config.get().get(section, {}), rest)
        if found is not _MISSING:
            return found, "global"

        # 3. a deprecated alias the user still sets (first one in
        #    sorted-key order, so the choice is deterministic)
        for alias in aliases_of(canonical):
            a_section, _, a_rest = alias.partition(".")
            if wiki_cfg is not None:
                found = _lookup_path(wiki_cfg, alias)
                if found is not _MISSING:
                    return found, "wiki"
            found = _lookup_path(self._config.get().get(a_section, {}), a_rest)
            if found is not _MISSING:
                return found, "global"

        # 4. registry default
        return default, "registry"

    def get(self, key: str) -> Any:
        """Resolved value for ``key`` (``None`` if unregistered)."""
        return self.resolve().get(key)

    def for_layer(self, layer: str) -> dict[str, Any]:
        """Resolved values for every key owned by ``layer``."""
        return {
            k: v for k, v in self.resolve().items() if PARAMS[k].layer == layer
        }

    def source(self, key: str) -> str:
        """Which scope supplied ``key``'s value: env/wiki/global/registry."""
        self.resolve()
        return (self._sources or {}).get(key, "registry")

    # ── Layer views ──────────────────────────────────────────────

    def foundation(self) -> FoundationParams:
        return FoundationParams(self.for_layer("foundation"))

    def kernel(self) -> KernelParams:
        return KernelParams(self.for_layer("kernel"))

    def apps(self) -> AppsParams:
        return AppsParams(self.for_layer("apps"))

    def interfaces(self) -> InterfacesParams:
        return InterfacesParams(self.for_layer("interfaces"))

    # ── Lifecycle (S2) ───────────────────────────────────────────

    def reload(self) -> set[str]:
        """Re-resolve, return changed keys, and notify listeners.

        Values are re-read *before* anything is applied, so a failure
        leaves the previous cache intact (nginx-style: bad config keeps
        the old one).
        """
        old = self._cache
        self._cache = None
        self._sources = None
        try:
            new = self.resolve()
        except Exception:
            # Keep serving the previous values on a bad re-read.
            self._cache = old
            self._sources = None
            raise
        if old is None:
            return set()
        changed = {k for k in new if old.get(k) != new[k]}
        if changed:
            for fn in list(self._listeners):
                fn(changed)
        return changed

    def on_change(self, fn: Callable[[set[str]], None]) -> Callable[[], None]:
        """Register a listener called with the changed keys after :meth:`reload`.

        Returns an unsubscribe callable. Consumers that hold expensive
        derived objects (an LLM client) register here; cheap values are
        read through :meth:`get` on each use instead.
        """
        self._listeners.append(fn)

        def _unsub() -> None:
            if fn in self._listeners:
                self._listeners.remove(fn)

        return _unsub


# One registry per wiki_root — a process-wide singleton would break
# multi-wiki (each wiki has its own .wiki-config.yaml).
_registry_cache: dict[str, ParamRegistry] = {}


def registry_for(wiki_root: Path | str | None = None) -> ParamRegistry:
    """Return the (cached) :class:`ParamRegistry` for ``wiki_root``."""
    cache_key = str(wiki_root) if wiki_root is not None else ""
    if cache_key not in _registry_cache:
        _registry_cache[cache_key] = ParamRegistry(wiki_root=wiki_root)
    return _registry_cache[cache_key]


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
