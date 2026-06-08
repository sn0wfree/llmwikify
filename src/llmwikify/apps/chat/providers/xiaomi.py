"""Xiaomi MiMo LLM Provider."""

from __future__ import annotations

from typing import Any

from .base import BaseLLMProvider


class XiaomiProvider(BaseLLMProvider):
    """Xiaomi MiMo provider using OpenAI-compatible API with api-key auth."""

    def provider_name(self) -> str:
        return "xiaomi"

    def default_base_url(self) -> str:
        return "https://token-plan-cn.xiaomimimo.com/v1"

    def default_model(self) -> str:
        return "mimo-v2.5-pro"

    def supported_models(self) -> list[str]:
        return [
            "mimo-v2.5-pro",
            "mimo-v2.5",
            "mimo-v2-flash",
            "mimo-v2-pro",
            "mimo-v2-omni",
        ]

    def from_config(self, config: dict) -> Any:
        from llmwikify.foundation.llm.streamable import StreamableLLMClient

        api_key = self._resolve_api_key(config)
        if not api_key:
            raise ValueError("Xiaomi MiMo API key not configured.")

        base_url = self._resolve_field(config, "base_url", self.default_base_url())
        model = self._resolve_field(config, "model", self.default_model())

        return StreamableLLMClient(
            provider=self.provider_name(),
            base_url=base_url,
            api_key=api_key,
            model=model,
            reasoning_split=True,
            auth_header="api-key",
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
            errors.append(f"Model '{model}' not supported. Choose from: {', '.join(self.supported_models())}")
        return errors
