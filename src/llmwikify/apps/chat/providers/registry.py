"""LLM Provider registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    from .base import LLMProvider

logger = logging.getLogger(__name__)

# Auto-imported below in the registration block — kept at top level
# so ruff E402 doesn't trip; the side-effecting ``register_provider``
# calls remain at the bottom of the file so any ``from
# .providers.registry import PROVIDERS`` sees a populated dict.
from .minimax import MiniMaxProvider  # noqa: E402
from .xiaomi import XiaomiProvider  # noqa: E402

PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_provider(provider_class: type[LLMProvider]) -> type[LLMProvider]:
    """Decorator to register a provider class."""
    # Auto-register based on provider_name()
    instance = provider_class()
    name = instance.provider_name()
    PROVIDERS[name] = provider_class
    return provider_class


def get_provider(name: str) -> LLMProvider:
    """Get a provider instance by name.

    LAL: legacy provider ids are resolved via the alias table
    in ``foundation.llm.resolver`` so existing wiki configs
    keep working after the rename.
    """
    from llmwikify.foundation.llm.resolver import apply_provider_alias
    canonical = apply_provider_alias(name)
    if canonical not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys()) or "none"
        raise ValueError(
            f"Unknown provider {name!r} (canonical: {canonical!r}). "
            f"Available: {available}"
        )
    return PROVIDERS[canonical]()


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(PROVIDERS.keys())


def create_llm(config: dict[str, Any]) -> StreamableLLMClient:
    """Create an LLM client based on config dict.

    The config should have a 'llm' key with provider, model, base_url, api_key etc.
    Falls back to the canonical default provider if not specified.
    """
    from llmwikify.foundation.llm.errors import LLMNotConfiguredError

    llm_cfg = config

    if not llm_cfg.get("enabled", False):
        raise LLMNotConfiguredError(
            "LLM is not enabled. Set llm.enabled=true in config."
        )

    import os
    provider_name = os.environ.get("LLM_PROVIDER", llm_cfg.get("provider", "minimax"))
    if provider_name is None:
        raise LLMNotConfiguredError(
            "No provider configured. Set provider in config or LLM_PROVIDER env."
        )

    provider = get_provider(provider_name)
    return provider.from_config(llm_cfg)


def get_default_provider() -> Any | None:
    """Resolve the default LLM provider from ``~/.llmwikify/llmwikify.json``.

    Behaviour (Option C, 2026-07-08):
      - config file missing or ``llm.enabled`` falsy → returns ``None``
        silently (legitimate "no LLM" mode).
      - ``llm.enabled=true`` + construction succeeds → returns the
        configured ``StreamableLLMClient``.
      - ``llm.enabled=true`` + construction fails → **raises**
        ``RuntimeError`` so callers can decide whether to fail fast
        or degrade via an explicit opt-out flag (CLI's
        ``--force-skip-dream``). Never silently swallows a config the
        user explicitly opted into.

    Reuses ``foundation.llm.client.load_llm_config`` (foundation layer,
    no import cycle) and ``create_llm`` (apps-layer provider
    abstraction). Previously this helper was referenced in
    ``WikiServer``'s docstring and in ``routes.py`` for the
    ``/v1/models`` model-name lookup but never defined; both call
    sites start working after this addition.
    """
    from llmwikify.foundation.llm.client import load_llm_config

    llm_cfg = load_llm_config()
    if not llm_cfg or not llm_cfg.get("enabled", False):
        return None
    try:
        return create_llm(llm_cfg)
    except Exception as exc:
        raise RuntimeError(
            f"LLM provider initialization failed (llm.enabled=true in "
            f"~/.llmwikify/llmwikify.json): {type(exc).__name__}: {exc}. "
            f"Fix the config, set llm.enabled=false, or pass "
            f"--force-skip-dream to suppress."
        ) from exc


# Auto-register built-in providers (must run AFTER the functions above
# are defined so ``register_provider`` is in scope).
register_provider(MiniMaxProvider)
register_provider(XiaomiProvider)
