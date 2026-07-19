"""Global + per-wiki LLM configuration manager.

v0.41: 默认配置从 ``foundation/templates/llmwikify.default.json`` 读取，
不再硬编码 DEFAULT_LLM_CONFIG。
"""
from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GLOBAL_CONFIG_DIR = Path.home() / ".llmwikify"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "llmwikify.json"

# 用户配置模板路径（包内）
_DEFAULT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "foundation" / "templates" / "llmwikify.default.json"


@lru_cache(maxsize=1)
def _load_default_template() -> dict[str, Any]:
    """Load default config from llmwikify.default.json template.

    Returns:
        The template as a dict, or empty dict if template is missing.
    """
    if not _DEFAULT_TEMPLATE_PATH.exists():
        logger.warning("Default template not found at %s", _DEFAULT_TEMPLATE_PATH)
        return {}
    try:
        return json.loads(_DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse default template: %s", exc)
        return {}


def get_default_llm_config() -> dict[str, Any]:
    """Get the default ``llm`` section from the template."""
    template = _load_default_template()
    return copy.deepcopy(template.get("llm", {}))


def get_default_research_config() -> dict[str, Any]:
    """Get the default ``research`` section from the template."""
    template = _load_default_template()
    return copy.deepcopy(template.get("research", {}))


class GlobalConfigManager:
    """Manages global and per-wiki LLM configuration.

    Config priority (highest to lowest):
        1. per-wiki .wiki-config.yaml llm section (if exists, v0.40 兼容)
        2. global ~/.llmwikify/llmwikify.json llm section (if exists)
        3. foundation/templates/llmwikify.default.json (template)

    v0.41: LLM config 默认值从 ``llmwikify.default.json`` 模板读取。
    """

    def __init__(self, agent_service_ref: Any = None):
        self._agent_service_ref = agent_service_ref

    def _ensure_global_dir(self) -> None:
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def load_global_config(self) -> dict[str, Any] | None:
        """Load the global config file (~/.llmwikify/llmwikify.json).

        Returns None if the file does not exist.
        """
        if not GLOBAL_CONFIG_FILE.exists():
            return None
        try:
            return json.loads(GLOBAL_CONFIG_FILE.read_text())
        except Exception as e:
            logger.warning("Failed to load global config: %s", e)
            return None

    def save_global_config(self, config: dict[str, Any]) -> None:
        """Save config to the global config file.

        Args:
            config: The llm config dict (enabled, provider, model, base_url, api_key, timeout).
                   Stored as {"llm": config} in the JSON file.
        """
        self._ensure_global_dir()
        payload = {"llm": config}
        GLOBAL_CONFIG_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def load_effective_llm_config(self, wiki_root: Path | None = None) -> dict[str, Any]:
        """Load the effective LLM config by merging global + per-wiki overrides.

        Priority: per-wiki .wiki-config.yaml > global config > template default
        """
        llm_cfg = get_default_llm_config()

        global_cfg = self.load_global_config()
        if global_cfg and "llm" in global_cfg:
            llm_cfg = _deep_merge(llm_cfg, global_cfg["llm"])

        if wiki_root:
            wiki_cfg = self._load_wiki_config(wiki_root)
            if wiki_cfg and "llm" in wiki_cfg:
                # v0.41: warn if wiki config still has llm section (deprecated)
                logger.warning(
                    "[config] .wiki-config.yaml 'llm' section is deprecated "
                    "since v0.41. Please move llm config to "
                    "~/.llmwikify/llmwikify.json instead. Ignoring wiki-level llm section."
                )
                # Still apply for backward compatibility, but warn
                llm_cfg = _deep_merge(llm_cfg, wiki_cfg["llm"])

        return llm_cfg

    def _load_wiki_config(self, wiki_root: Path) -> dict[str, Any] | None:
        """Load per-wiki config from .wiki-config.yaml.

        v0.41: LLM section is deprecated but still read for backward compat.
        Other sections (directories, database, wikis) remain valid.
        """
        config_path = wiki_root / ".wiki-config.yaml"
        if not config_path.exists():
            return None
        try:
            import yaml
            return yaml.safe_load(config_path.read_text()) or {}
        except Exception as e:
            logger.warning("Failed to load wiki config: %s", e)
            return None

    def mask_api_key(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of config with api_key masked for safe display."""
        masked = copy.deepcopy(config)
        api_key = masked.get("api_key", "")
        if api_key:
            if api_key.startswith("env:"):
                masked["api_key"] = "env:***"
            elif len(api_key) > 8:
                masked["api_key"] = api_key[:4] + "***" + api_key[-4:]
            else:
                masked["api_key"] = "***"
        return masked

    def reload(self) -> None:
        """Signal the agent service to reload its LLM client on next request."""
        if self._agent_service_ref is not None:
            service = self._agent_service_ref()
            if service is not None:
                service._llm = None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dicts, override taking precedence."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


_global_manager: GlobalConfigManager | None = None


def get_global_config_manager(agent_service_ref: Any = None) -> GlobalConfigManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = GlobalConfigManager(agent_service_ref)
    return _global_manager
