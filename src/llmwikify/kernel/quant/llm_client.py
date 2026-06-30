"""Backward-compat shim: build_llm_client 已下沉 foundation/llm/client.

历史: build_llm_client + load_llm_config + CONFIG_PATH 从
kernel/quant/llm_client.py (C2) 搬到 foundation/llm/client.py
(G+Y commit 4: LLM 基础设施下沉 foundation 层)。

本 shim 保留为 backward-compat re-export, 让旧 import path 仍工作:
    from llmwikify.kernel.quant.llm_client import build_llm_client
    from llmwikify.kernel.quant.llm_client import load_llm_config, CONFIG_PATH

新代码应直接:
    from llmwikify.foundation.llm.client import build_llm_client, load_llm_config
"""
from llmwikify.foundation.llm.client import (  # noqa: F401
    _PROVIDER_INFO,
    CONFIG_PATH,
    _resolve_provider_info,
    build_llm_client,
    load_llm_config,
)

__all__ = [
    "CONFIG_PATH",
    "load_llm_config",
    "build_llm_client",
    "_PROVIDER_INFO",
    "_resolve_provider_info",
]
