"""Provider model registry — supported model names per provider.

LAL: subagent drivers validate ``actor.model`` against the
provider's supported model list before applying an override on
top of the inherited ``LLMSpec.model``. PR 2 introduces this
helper; PR 3 will tighten the validation to fail-fast at workflow
startup instead of at subagent spawn time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# Provider id -> list of supported model names. Keep in sync with
# the per-provider ``supported_models()`` methods. PR 4 will move
# this knowledge into the provider registry so the duplication goes
# away.
_PROVIDER_SUPPORTED_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ],
    "minimax": [
        "minimax-M3",
        "minimax-M2.7",
        "minimax-M2.7-highspeed",
        "minimax-M2.5",
        "minimax-M2.5-highspeed",
        "minimax-M2.1",
        "minimax-M2.1-highspeed",
        "minimax-M2",
    ],
    "xiaomi": [
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2-flash",
        "mimo-v2-pro",
        "mimo-v2-omni",
    ],
    # ollama / lmstudio: too many model names to enumerate; empty
    # list means "no validation, any model name is accepted".
    "ollama": [],
    "lmstudio": [],
}


def get_supported_models(provider: str) -> list[str]:
    """Return the supported model names for ``provider``.

    Returns an empty list when the provider is unknown or when
    validation is intentionally disabled (e.g. for ollama where
    the model name is user-chosen at install time).

    Aliases are resolved first, so legacy ids (``minimax``) work
    the same as the canonical ones.
    """
    # Resolve alias to keep call sites simple.
    from llmwikify.foundation.llm.resolver import apply_provider_alias
    canonical = apply_provider_alias(provider)
    return list(_PROVIDER_SUPPORTED_MODELS.get(canonical, []))


__all__ = ["get_supported_models"]
