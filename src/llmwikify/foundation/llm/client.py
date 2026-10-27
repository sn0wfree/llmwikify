"""foundation/llm/client — LLM client construction from ~/.llmwikify/llmwikify.json.

下沉: 从 kernel/quant/llm_client.py (C2) 搬到 foundation/llm/client.py
(G+Y commit 4)。build_llm_client 是 LLM 基础设施的一部分, 应该在 foundation
层, 而不是 kernel 层。

v0.41: Provider 元数据 (base_url, auth_scheme) 改从 providers.yaml 读取，
删除硬编码的 _PROVIDER_INFO。build_llm_client 改为薄包装，调用 resolver
解析配置。

Dual-stack merge (2026-10-23): construction shares the process-level
client memo in ``llm/base.py`` so repeated ``build_llm_client()`` calls
do not rebuild the HTTP client (same semantics as
``LLMClient.from_config``).

依赖: foundation/llm/streamable.py (StreamableLLMClient)
foundation/llm/resolver.py (resolve_chat_llm)

Canonical imports:
    from llmwikify.foundation.llm.client import build_llm_client, load_llm_config
    from llmwikify.foundation.llm.client import CONFIG_PATH
"""

from __future__ import annotations

import json
import logging
import threading
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

# Separate memo namespace from LLMClient.from_config: identical config
# keys may still map to different classes (LLMClient vs
# StreamableLLMClient). The lock is shared to keep teardown ordering
# simple.
_BUILD_MEMO: dict[str, Any] = {}
_BUILD_MEMO_LOCK = threading.Lock()


def _build_memo_key(llm_cfg: dict[str, Any]) -> str:
    from .base import _client_memo_key

    return "build:" + _client_memo_key(llm_cfg)


def clear_build_llm_client_memo() -> None:
    """Drop cached build_llm_client results (config reload)."""
    with _BUILD_MEMO_LOCK:
        _BUILD_MEMO.clear()


def build_llm_client(
    config: dict[str, Any] | None = None,
    model: str | None = None,
    config_path: Path | None = None,
) -> Any:
    """Build a ``StreamableLLMClient`` from user config.

    v0.41: This is now a thin wrapper around ``resolve_chat_llm()``.
    All provider metadata (base_url, auth_scheme, default_model) is
    loaded from ``providers.yaml``; no hardcoded defaults remain.

    Results are memoized per config/env fingerprint
    (``_client_memo_key``) so repeated calls return the same client.
    Call :func:`clear_build_llm_client_memo` (or
    ``clear_llm_client_memo`` + this one) after config reload.

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

    memo_key = _build_memo_key(wrapped_config["llm"])
    with _BUILD_MEMO_LOCK:
        hit = _BUILD_MEMO.get(memo_key)
        if hit is not None:
            return hit

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
    client = StreamableLLMClient.from_spec(spec)
    with _BUILD_MEMO_LOCK:
        _BUILD_MEMO[memo_key] = client
    return client


__all__ = [
    "CONFIG_PATH",
    "load_llm_config",
    "build_llm_client",
    "clear_build_llm_client_memo",
]
