"""foundation/llm/client — LLM client construction from ~/.llmwikify/llmwikify.json.

下沉: 从 kernel/quant/llm_client.py (C2) 搬到 foundation/llm/client.py
(G+Y commit 4)。build_llm_client 是 LLM 基础设施的一部分, 应该在 foundation
层, 而不是 kernel 层。

依赖: foundation/llm/streamable.py (StreamableLLMClient)

Canonical imports:
    from llmwikify.foundation.llm.client import build_llm_client, load_llm_config
    from llmwikify.foundation.llm.client import CONFIG_PATH
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── Config location ─────────────────────────────────────────────────

CONFIG_PATH: Path = Path.home() / ".llmwikify" / "llmwikify.json"


# ─── Provider info table (C2: replaces hardcoded "minimax" / "bearer") ─
#
# Maps provider name → (default_base_url, auth_header).
# Used by build_llm_client to fill in config gaps. Adding a new provider?
# Add a row here. (Full provider metadata lives in apps/chat/providers/
# for the chat agent; for simple client construction this is enough.)

_PROVIDER_INFO: dict[str, tuple[str, str]] = {
    # provider_name → (default_base_url, auth_header)
    "minimax": ("https://api.minimaxi.com/v1", "bearer"),
    "xiaomi": ("https://api.xiaomi.com/v1", "bearer"),
    "openai": ("https://api.openai.com/v1", "bearer"),
    "anthropic": ("https://api.anthropic.com/v1", "x-api-key"),
}


# ─── Config loading ──────────────────────────────────────────────────


def load_llm_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load the ``[llm]`` section of ``~/.llmwikify/llmwikify.json``.

    Args:
        config_path: Override config file path (default: ~/.llmwikify/llmwikify.json).
                     Mainly for tests.

    Returns:
        The ``llm`` section as a dict, or ``{}`` if the file is missing
        or unparseable.
    """
    path = config_path or CONFIG_PATH
    if not path.exists():
        logger.warning("LLM config not found at %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return {}
    return data.get("llm", {})


# ─── Client construction ─────────────────────────────────────────────


def _resolve_provider_info(provider: str) -> tuple[str, str]:
    """Look up (default_base_url, auth_header) for a provider.

    C2: replaces the old hardcoded `auth_header = "bearer" if ... else "bearer"`
    no-op with a real lookup.

    Args:
        provider: Provider name from config (e.g., "minimax", "xiaomi").

    Returns:
        (default_base_url, auth_header) tuple. Falls back to
        (generic OpenAI URL, "bearer") if the provider is unknown.
        Logs a warning for unknown providers (don't silently default).
    """
    if provider in _PROVIDER_INFO:
        return _PROVIDER_INFO[provider]
    logger.warning(
        "[llm_client] unknown provider %r; falling back to OpenAI defaults. "
        "Add an entry to _PROVIDER_INFO if you want custom base_url/auth_header.",
        provider,
    )
    return _PROVIDER_INFO["openai"]


def build_llm_client(
    config: dict[str, Any] | None = None,
    model: str | None = None,
    config_path: Path | None = None,
) -> Any:
    """Build a ``StreamableLLMClient`` from user config.

    Args:
        config: Pre-loaded config dict. If None, loads from
                ``~/.llmwikify/llmwikify.json`` (or `config_path`).
        model: Override model name (default: config's ``model`` field).
        config_path: Override config file path (mainly for tests).

    Returns:
        Configured ``StreamableLLMClient`` instance.

    Raises:
        RuntimeError: If LLM is disabled in config, provider is missing,
            or api_key is not configured.
    """
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    if config is None:
        config = load_llm_config(config_path=config_path)

    if not config.get("enabled"):
        raise RuntimeError(
            f"LLM is disabled in {config_path or CONFIG_PATH}. "
            "Set llm.enabled=true to enable."
        )

    # C2: provider is REQUIRED (was hardcoded to "minimax" in pre-C2).
    # If the config has no provider, fail loudly rather than silently
    # fall back to minimax.
    provider = config.get("provider")
    if not provider:
        raise RuntimeError(
            f"Missing 'provider' in {config_path or CONFIG_PATH}. "
            f"Set llm.provider to one of: {', '.join(_PROVIDER_INFO.keys())}"
        )

    # C2: auth_header from provider-info table (was no-op hardcoded "bearer").
    default_base_url, auth_header = _resolve_provider_info(provider)
    base_url = config.get("base_url") or default_base_url
    chosen_model = model or config.get("model") or "MiniMax-M2.7"
    api_key = config.get("api_key", "")
    timeout = config.get("timeout", 600)

    if not api_key:
        raise RuntimeError(
            f"Missing api_key in {config_path or CONFIG_PATH}. Set llm.api_key first."
        )

    logger.info(
        "[llm_client] provider=%s model=%s base_url=%s timeout=%s",
        provider,
        chosen_model,
        base_url,
        timeout,
    )
    return StreamableLLMClient(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=chosen_model,
        auth_header=auth_header,
        reasoning_split=True,
        request_timeout_seconds=float(timeout),
    )


__all__ = ["CONFIG_PATH", "load_llm_config", "build_llm_client", "_PROVIDER_INFO"]
