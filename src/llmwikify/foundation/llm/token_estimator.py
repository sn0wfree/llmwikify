"""Token estimator — tiktoken with fallback to heuristic char-ratio estimation.

When tiktoken is available, uses model-specific encoding for accurate counts.
Falls back to len(text) // 3 for unknown models or when tiktoken is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level encoding cache
_encoding_cache: dict[str, Any | None] = {}


def _get_tiktoken_encoding(model: str) -> Any | None:
    """Get tiktoken encoding for a model, with caching."""
    if model in _encoding_cache:
        return _encoding_cache[model]
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model(model)
        _encoding_cache[model] = enc
        return enc
    except (KeyError, ImportError):
        _encoding_cache[model] = None
        return None


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in text.

    Uses tiktoken when available for the model, otherwise falls back to
    a heuristic of 1 token per 3 characters (mixed language estimate).
    """
    if not text:
        return 0
    enc = _get_tiktoken_encoding(model)
    if enc is not None:
        return len(enc.encode(text))
    # Fallback: mixed language heuristic (1 token ~ 3 chars)
    return max(1, len(text) // 3)


def count_messages(messages: list[dict[str, str]], model: str = "gpt-4o") -> int:
    """Estimate total token count for a messages list (including overhead).

    Each message has ~4 tokens of framing overhead (role, separators).
    Supports both string content and multipart content (list of dicts).
    """
    total = 0
    for msg in messages:
        total += 4  # message framing tokens
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content, model)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += count_tokens(part["text"], model)
    return total
