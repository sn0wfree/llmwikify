"""foundation/llm/client — LLM client construction from ~/.llmwikify/llmwikify.json.

下沉: 从 kernel/quant/llm_client.py (C2) 搬到 foundation/llm/client.py
(G+Y commit 4)。build_llm_client 是 LLM 基础设施的一部分, 应该在 foundation
层, 而不是 kernel 层。

v0.41: Provider 元数据 (base_url, auth_scheme) 改从 providers.yaml 读取，
删除硬编码的 _PROVIDER_INFO。build_llm_client 改为薄包装，调用 resolver
解析配置。

依赖: foundation/llm/streamable.py (StreamableLLMClient)
foundation/llm/resolver.py (resolve_chat_llm)

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


def build_llm_client(
    config: dict[str, Any] | None = None,
    model: str | None = None,
    config_path: Path | None = None,
) -> Any:
    """Build a ``StreamableLLMClient`` from user config.

    v0.41: This is now a thin wrapper around ``resolve_chat_llm()``.
    All provider metadata (base_url, auth_scheme, default_model) is
    loaded from ``providers.yaml``; no hardcoded defaults remain.

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
    from llmwikify.foundation.llm.resolver import resolve_chat_llm
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    if config is None:
        config = load_llm_config(config_path=config_path)

    if not config.get("enabled"):
        raise RuntimeError(
            f"LLM is disabled in {config_path or CONFIG_PATH}. "
            "Set llm.enabled=true to enable."
        )

    # Wrap config dict to match resolve_chat_llm expected format
    wrapped_config: dict[str, Any] = {"llm": dict(config)}
    if model is not None:
        wrapped_config["llm"]["model"] = model

    spec = resolve_chat_llm(wrapped_config)

    if not spec.api_key:
        raise RuntimeError(
            f"Missing api_key in {config_path or CONFIG_PATH}. Set llm.api_key first."
        )

    logger.info(
        "[llm_client] provider=%s model=%s base_url=%s timeout=%s",
        spec.provider,
        spec.model,
        spec.base_url,
        spec.timeout,
    )
    return StreamableLLMClient.from_spec(spec)


__all__ = ["CONFIG_PATH", "load_llm_config", "build_llm_client"]
