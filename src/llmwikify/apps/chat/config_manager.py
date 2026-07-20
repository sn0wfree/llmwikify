"""Global + per-wiki LLM configuration manager.

v0.41: 默认配置从 ``foundation/templates/llmwikify.default.json`` 读取，
不再硬编码 DEFAULT_LLM_CONFIG。

v0.42: 重构为 foundation.config.Config + foundation.utils 的薄包装。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llmwikify.foundation.config import Config
from llmwikify.foundation.utils import deep_merge, mask_api_key

logger = logging.getLogger(__name__)


def get_default_llm_config() -> dict[str, Any]:
    """Get the default ``llm`` section from the template."""
    return Config().get_default("llm")


def get_default_research_config() -> dict[str, Any]:
    """Get the default ``research`` section from the template."""
    return Config().get_default("research")


class ConfigManager:
    """Config + agent service reload.

    This is the apps-layer wrapper around foundation.config.Config.
    It adds:
    - load_effective_llm_config(): merge template + global + per-wiki
    - reload(): clear cache + signal agent service to reload LLM client
    - mask_api_key(): delegate to foundation.utils.mask_api_key

    Usage::

        from llmwikify.apps.chat.config_manager import ConfigManager

        manager = ConfigManager(agent_service_ref=lambda: service)
        llm_cfg = manager.load_effective_llm_config(wiki_root)
    """

    def __init__(self, agent_service_ref: Any = None):
        self._config = Config()
        self._agent_service_ref = agent_service_ref

    def load_global_config(self) -> dict[str, Any] | None:
        """Load the global config file (~/.llmwikify/llmwikify.json).

        Returns None if the file does not exist.
        """
        result = self._config.get()
        return result if result else None

    def save_global_config(self, data: dict[str, Any]) -> None:
        """Save LLM config to the global config file.

        Args:
            data: The llm config dict. Stored as {"llm": data} in JSON.
        """
        self._config.save(data, section="llm")

    def load_effective_llm_config(self, wiki_root: Path | None = None) -> dict[str, Any]:
        """Load the effective LLM config by merging global + per-wiki overrides.

        Priority: per-wiki .wiki-config.yaml > global config > template default
        """
        llm_cfg = self._config.get_default("llm")

        global_cfg = self._config.get("llm")
        if global_cfg:
            llm_cfg = deep_merge(llm_cfg, global_cfg)

        if wiki_root:
            wiki_cfg = self._config.get_wiki_config(wiki_root)
            if wiki_cfg and "llm" in wiki_cfg:
                logger.warning(
                    "[config] .wiki-config.yaml 'llm' section is deprecated "
                    "since v0.41. Please move llm config to "
                    "~/.llmwikify/llmwikify.json instead. Ignoring wiki-level llm section."
                )
                llm_cfg = deep_merge(llm_cfg, wiki_cfg["llm"])

        return llm_cfg

    def mask_api_key(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of config with api_key masked for safe display."""
        return mask_api_key(data)

    def reload(self) -> None:
        """Clear cache + signal agent service to reload LLM client."""
        self._config.reload()
        if self._agent_service_ref is not None:
            service = self._agent_service_ref()
            if service is not None:
                service._llm = None


# Backward-compatible alias
GlobalConfigManager = ConfigManager

_global_manager: ConfigManager | None = None


def get_global_config_manager(agent_service_ref: Any = None) -> ConfigManager:
    """Get or create the global ConfigManager singleton.

    .. deprecated:: Use ``ConfigManager()`` directly.
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = ConfigManager(agent_service_ref)
    return _global_manager


__all__ = [
    "ConfigManager",
    "GlobalConfigManager",
    "get_global_config_manager",
    "get_default_llm_config",
    "get_default_research_config",
]
