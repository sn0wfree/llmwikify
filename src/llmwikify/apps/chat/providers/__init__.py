"""LLM Provider abstraction layer."""

from .abc import (
    LLMProviderABC,
    ProviderConfig,
    RetryMode,
    ThinkingStyle,
)
from .base import BaseLLMProvider, LLMProvider
from .registry import create_llm, get_provider, list_providers, register_provider
from .xiaomi import XiaomiProvider

__all__ = [
    # Protocol + base (legacy, used by MiniMax/Xiaomi)
    "LLMProvider",
    "BaseLLMProvider",
    "XiaomiProvider",
    # ABC + dataclass + enums (Phase 16, for new providers)
    "LLMProviderABC",
    "ProviderConfig",
    "RetryMode",
    "ThinkingStyle",
    # Registry
    "register_provider",
    "get_provider",
    "list_providers",
    "create_llm",
]
