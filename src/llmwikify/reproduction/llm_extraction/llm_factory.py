"""LLM client factory: load config from ~/.llmwikify/llmwikify.json.

Provides a single ``build_default_client()`` helper that reads the user-level
config and instantiates a ``StreamableLLMClient`` matching the
``[llm]`` section. Centralizes config parsing so the rest of the pipeline
can ask for a ready-to-use client.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".llmwikify" / "llmwikify.json"


def load_llm_config() -> dict[str, Any]:
    """Load the ``[llm]`` section of ``~/.llmwikify/llmwikify.json``.

    Returns empty dict if file missing or unparseable.
    """
    if not CONFIG_PATH.exists():
        logger.warning("LLM config not found at %s", CONFIG_PATH)
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", CONFIG_PATH, exc)
        return {}
    return data.get("llm", {})


def build_default_client(model: str | None = None):
    """Build a ``StreamableLLMClient`` from user config.

    Args:
        model: Override model name (default: config's ``model`` field).

    Returns:
        Configured ``StreamableLLMClient`` instance.

    Raises:
        RuntimeError: If config missing or required fields absent.
    """
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    cfg = load_llm_config()
    if not cfg.get("enabled"):
        raise RuntimeError(
            "LLM is disabled in ~/.llmwikify/llmwikify.json. "
            "Set llm.enabled=true to enable."
        )

    provider = cfg.get("provider", "minimax")
    base_url = cfg.get("base_url", "")
    api_key = cfg.get("api_key", "")
    chosen_model = model or cfg.get("model", "MiniMax-M2.7")
    timeout = cfg.get("timeout", 600)
    auth_header = "bearer" if "minimax" in provider else "bearer"

    if not api_key:
        raise RuntimeError(
            f"Missing api_key in {CONFIG_PATH}. Set llm.api_key first."
        )

    logger.info(
        "[llm] provider=%s model=%s base_url=%s timeout=%s",
        provider, chosen_model, base_url, timeout,
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
