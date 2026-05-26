"""Provider abstraction layer for LLM clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..adapters import StreamableLLMClient


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Each provider knows how to:
    - Create a StreamableLLMClient from a config dict
    - Validate its own config and report invalid fields
    - Provide default values (model, base_url)
    - List supported models
    """

    def from_config(self, config: dict) -> "StreamableLLMClient":
        """Create an LLM client from a full config dict."""
        ...

    def validate_config(self, config: dict) -> list[str]:
        """Validate config and return list of error messages (empty = valid)."""
        ...

    def default_model(self) -> str:
        """Return the default model name for this provider."""
        ...

    def supported_models(self) -> list[str]:
        """Return list of supported model names for this provider."""
        ...

    def default_base_url(self) -> str:
        """Return the default base URL for this provider."""
        ...

    def provider_name(self) -> str:
        """Return the provider identifier string."""
        ...


class BaseLLMProvider:
    """Base class with shared utility methods."""

    def _resolve_api_key(self, config: dict) -> str:
        """Resolve API key from config, supporting env:VAR_NAME syntax."""
        import os

        api_key = config.get("api_key", "")
        if isinstance(api_key, str) and api_key.startswith("env:"):
            api_key = os.environ.get(api_key[4:], "")
        api_key = os.environ.get("LLM_API_KEY", api_key)
        return api_key

    def _resolve_field(self, config: dict, field: str, default: str) -> str:
        """Resolve a field from config with environment variable override."""
        env_key = f"LLM_{field.upper()}"
        import os
        return os.environ.get(env_key, config.get(field, default))