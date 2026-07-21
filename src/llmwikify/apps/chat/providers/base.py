"""Provider abstraction layer for LLM clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from llmwikify.foundation.llm.streamable import StreamableLLMClient


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Each provider knows how to:
    - Create a StreamableLLMClient from a config dict
    - Validate its own config and report invalid fields
    - Provide default values (model, base_url)
    - List supported models
    """

    def from_config(self, config: dict) -> StreamableLLMClient:
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
    """Shared base for OpenAI-compatible LLM providers.

    Subclasses must set ``_PROVIDER_ID`` and optionally override:
    - ``_build_legacy_client()``: provider-specific kwargs for legacy path
    - ``validate_config()``: add provider-specific validation
    """

    _PROVIDER_ID: str = ""

    def provider_name(self) -> str:
        return self._PROVIDER_ID

    def _metadata(self) -> dict:
        from llmwikify.foundation.llm.resolver import get_provider_metadata
        return get_provider_metadata(self._PROVIDER_ID)

    def default_base_url(self) -> str:
        return self._metadata().get("base_url", "")

    def default_model(self) -> str:
        return self._metadata().get("default_model", "")

    def supported_models(self) -> list[str]:
        return list(self._metadata().get("supported_models", []))

    def from_config(self, config: dict) -> StreamableLLMClient:
        from llmwikify.foundation.llm.resolver import resolve_chat_llm, resolver_enabled
        from llmwikify.foundation.llm.streamable import StreamableLLMClient

        if resolver_enabled():
            wrapped = dict(config)
            wrapped.setdefault("provider", self.provider_name())
            spec = resolve_chat_llm({"llm": wrapped})
            if not spec.api_key:
                raise ValueError(f"{self._PROVIDER_ID} API key not configured.")
            return StreamableLLMClient.from_spec(spec)

        api_key = self._resolve_api_key(config)
        if not api_key:
            raise ValueError(f"{self._PROVIDER_ID} API key not configured.")

        base_url = self._resolve_field(config, "base_url", self.default_base_url())
        model = self._resolve_field(config, "model", self.default_model())

        return self._build_legacy_client(config, base_url, api_key, model)

    def _build_legacy_client(
        self, config: dict, base_url: str, api_key: str, model: str,
    ) -> StreamableLLMClient:
        """Build client for the legacy (non-resolver) path.

        Override in subclasses for provider-specific kwargs.
        """
        from llmwikify.foundation.llm.streamable import StreamableLLMClient
        return StreamableLLMClient(
            provider=self.provider_name(),
            base_url=base_url,
            api_key=api_key,
            model=model,
            reasoning_split=config.get("reasoning_split", True),
            context_window=config.get("context_window"),
            budget_on_exceed=config.get("budget_on_exceed", "warn"),
        )

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        api_key = self._resolve_api_key(config)
        if not api_key:
            errors.append("API key is required")
        model = config.get("model", "")
        if model and model not in self.supported_models():
            errors.append(
                f"Model '{model}' not supported. "
                f"Choose from: {', '.join(self.supported_models())}"
            )
        return errors

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
