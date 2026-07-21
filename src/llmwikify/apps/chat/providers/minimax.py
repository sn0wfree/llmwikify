"""MiniMax LLM Provider.

v0.41: Provider 元数据（base_url、default_model、supported_models）
从 ``foundation/llm/providers.yaml`` 读取，代码中不再硬编码。

LAL (PR 4): provider id renamed from ``minimax`` to
``minimax`` (lowercased to match the host domain
``api.minimaxi.com`` and to break the visual confusion with
a different large-model company). The legacy id is still
accepted as an alias via ``foundation.llm.resolver`` for
back-compat with existing wiki configs.
"""

from __future__ import annotations

from .base import BaseLLMProvider


class MiniMaxProvider(BaseLLMProvider):
    """MiniMax provider using OpenAI-compatible API.

    v0.41: All defaults (base_url, default_model, supported_models) are
    loaded from ``providers.yaml`` via ``get_provider_metadata()``.

    LAL: ``from_config`` delegates to the single resolver when
    ``LLM_USE_RESOLVER`` is enabled, ensuring provider-internal
    defaults stay aligned with the rest of the LAL surface.
    """

    _PROVIDER_ID = "minimax"

    def validate_config(self, config: dict) -> list[str]:
        errors = super().validate_config(config)
        if not config.get("base_url"):
            errors.append("Base URL is required")
        return errors
