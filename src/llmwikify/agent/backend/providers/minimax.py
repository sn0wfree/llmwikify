"""MiniMax LLM Provider."""

from __future__ import annotations

from typing import Any

from .base import BaseLLMProvider


class MiniMaxProvider(BaseLLMProvider):
    """MiniMax provider using OpenAI-compatible API."""

    def provider_name(self) -> str:
        return "minimax"

    def default_base_url(self) -> str:
        return "https://api.minimaxi.com/v1"

    def default_model(self) -> str:
        return "MiniMax-M2.7"

    def supported_models(self) -> list[str]:
        return [
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.1",
            "MiniMax-M2.1-highspeed",
            "MiniMax-M2",
        ]

    def from_config(self, config: dict) -> "StreamableLLMClient":
        from ..adapters import StreamableLLMClient

        api_key = self._resolve_api_key(config)
        if not api_key:
            raise ValueError("MiniMax API key not configured.")

        base_url = self._resolve_field(config, "base_url", self.default_base_url())
        model = self._resolve_field(config, "model", self.default_model())

        reasoning_split = config.get("reasoning_split", True)

        return StreamableLLMClient(
            provider=self.provider_name(),
            base_url=base_url,
            api_key=api_key,
            model=model,
            reasoning_split=reasoning_split,
        )

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        api_key = self._resolve_api_key(config)
        if not api_key:
            errors.append("API key is required")
        base_url = config.get("base_url", "")
        if not base_url:
            errors.append("Base URL is required")
        model = config.get("model", "")
        if model and model not in self.supported_models():
            errors.append(f"Model '{model}' not supported. Choose from: {', '.join(self.supported_models())}")
        return errors