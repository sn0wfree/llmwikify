"""LLM Provider registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import LLMProvider
    from llmwikify.llm.streamable import StreamableLLMClient


PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_provider(provider_class: type[LLMProvider]) -> type[LLMProvider]:
    """Decorator to register a provider class."""
    # Auto-register based on provider_name()
    instance = provider_class()
    name = instance.provider_name()
    PROVIDERS[name] = provider_class
    return provider_class


def get_provider(name: str) -> LLMProvider:
    """Get a provider instance by name."""
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys()) or "none"
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return PROVIDERS[name]()


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(PROVIDERS.keys())


def create_llm(config: dict[str, Any]) -> StreamableLLMClient:
    """Create an LLM client based on config dict.

    The config should have a 'llm' key with provider, model, base_url, api_key etc.
    Falls back to 'minimax' provider if not specified.
    """
    llm_cfg = config

    if not llm_cfg.get("enabled", False):
        raise ValueError("LLM is not enabled. Set llm.enabled=true in config.")

    import os
    provider_name = os.environ.get("LLM_PROVIDER", llm_cfg.get("provider", "minimax"))

    provider = get_provider(provider_name)
    return provider.from_config(llm_cfg)


# Auto-register built-in providers
from .minimax import MiniMaxProvider
from .xiaomi import XiaomiProvider

register_provider(MiniMaxProvider)
register_provider(XiaomiProvider)