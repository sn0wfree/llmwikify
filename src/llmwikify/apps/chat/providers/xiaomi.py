"""Xiaomi MiMo LLM Provider.

v0.41: Provider 元数据（base_url、default_model、supported_models）
从 ``foundation/llm/providers.yaml`` 读取，代码中不再硬编码。
"""

from __future__ import annotations

from llmwikify.foundation.llm.streamable import StreamableLLMClient

from .base import BaseLLMProvider


class XiaomiProvider(BaseLLMProvider):
    """Xiaomi MiMo provider using OpenAI-compatible API with api-key auth.

    v0.41: All defaults loaded from ``providers.yaml``.
    """

    _PROVIDER_ID = "xiaomi"

    def _build_legacy_client(
        self, config: dict, base_url: str, api_key: str, model: str,
    ) -> StreamableLLMClient:
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
