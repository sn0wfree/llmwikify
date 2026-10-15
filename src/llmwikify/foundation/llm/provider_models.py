"""Provider model registry — supported model names per provider.

v0.41: All provider metadata (supported_models, base_url, auth_scheme,
default_model, context_windows, reasoning_split) is loaded from
``providers.yaml``. This module is a thin accessor over the YAML data.

LAL: subagent drivers validate ``actor.model`` against the
provider's supported model list before applying an override on
top of the inherited ``LLMSpec.model``.
"""

from __future__ import annotations


def get_supported_models(provider: str) -> list[str]:
    """Return the supported model names for ``provider``.

    Returns an empty list when the provider is unknown or when
    validation is intentionally disabled (e.g. for ollama where
    the model name is user-chosen at install time).

    Aliases are resolved first, so legacy ids (``minimax``) work
    the same as the canonical ones.
    """
    from llmwikify.foundation.llm.resolver import (
        apply_provider_alias,
        get_provider_metadata,
    )

    canonical = apply_provider_alias(provider)
    meta = get_provider_metadata(canonical)
    return list(meta.get("supported_models", []))


__all__ = ["get_supported_models"]
