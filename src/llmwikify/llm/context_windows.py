"""Model context window database + multi-level fallback resolver.

Data source: LiteLLM model_prices_and_context_window.json
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Built-in mapping table
CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    # Anthropic
    "claude-3-5-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    # Ollama / Local
    "llama3": 8_192,
    "llama3.1": 131_072,
    "llama3.2": 131_072,
    "qwen2.5": 131_072,
    "deepseek-coder": 16_384,
    "mistral": 32_768,
    "phi3": 131_072,
    # MiniMax
    "MiniMax-M2.7": 1_000_000,
    "MiniMax-M2.5": 1_000_000,
    # Fallback
    "default": 32_768,
}

# Regex to extract context window from model name (e.g. "llama3-8k" -> 8192)
_MODEL_CTX_RE = re.compile(r"[-_](\d+)[kK]$")


def _extract_ctx_from_name(model: str) -> int | None:
    """Try to extract context window from model name (e.g. llama3-8k -> 8192)."""
    m = _MODEL_CTX_RE.search(model)
    if m:
        return int(m.group(1)) * 1024
    return None


def probe_provider_api(
    model: str, base_url: str, api_key: str
) -> int | None:
    """Call provider's /v1/models/{model} to probe context window.

    Returns context window size if found, None otherwise.
    Supports vLLM (max_model_len), and other OpenAI-compatible providers.
    """
    try:
        import requests

        resp = requests.get(
            f"{base_url}/v1/models/{model}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        if resp.ok:
            data = resp.json()
            for key in ("context_length", "max_model_len", "max_context_length"):
                val = data.get(key)
                if isinstance(val, int) and val > 0:
                    return val
    except Exception as e:
        logger.debug("Provider API probe failed: %s", e)
    return None


def ask_llm_context_window(llm_client: Any) -> int | None:
    """Ask the LLM its own context window size (debug mode only).

    This is unreliable — many models don't know or will hallucinate.
    Use only as a sanity check, not as primary source.
    """
    try:
        resp = llm_client.chat(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "What is your maximum context window size in tokens? "
                        "Reply with ONLY a number, nothing else."
                    ),
                }
            ],
            max_tokens=10,
            temperature=0,
        )
        nums = re.findall(r"\d+", resp.strip())
        if nums:
            val = int(nums[0])
            if val > 0:
                return val
    except Exception as e:
        logger.debug("LLM context window query failed: %s", e)
    return None


def resolve_context_window(
    model: str,
    config_override: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    llm_client: Any | None = None,
    debug: bool = False,
) -> int:
    """Resolve context window with multi-level fallback.

    Priority:
    1. User config (config_override)
    2. Provider API probe (base_url + api_key)
    3. Model name inference (e.g. "llama3-8k" -> 8192)
    4. Built-in lookup table
    5. LLM self-query (only when debug=True)
    6. Conservative default
    """
    # Level 1: User config
    if config_override is not None:
        logger.info("Context window from config: %d", config_override)
        return config_override

    # Level 2: Provider API probe
    if base_url and api_key:
        probed = probe_provider_api(model, base_url, api_key)
        if probed is not None:
            logger.info("Context window from provider API: %d", probed)
            return probed

    # Level 3: Model name inference
    inferred = _extract_ctx_from_name(model)
    if inferred is not None:
        logger.info("Context window from model name: %d", inferred)
        return inferred

    # Level 4: Built-in lookup table
    mapped = CONTEXT_WINDOWS.get(model)
    if mapped is not None:
        logger.info("Context window from lookup table: %d", mapped)
        return mapped

    # Level 5: LLM self-query (debug only)
    if debug and llm_client is not None:
        asked = ask_llm_context_window(llm_client)
        if asked is not None:
            logger.warning(
                "Context window from LLM self-report (unverified): %d", asked
            )
            return asked

    # Level 6: Conservative default
    default = CONTEXT_WINDOWS["default"]
    logger.info("Context window using default: %d", default)
    return default
