"""Normalize an LLM client response into plain text.

``LLMClient.chat`` / ``StreamableLLMClient.achat`` are declared ``-> str``
(``foundation/llm/base.py``, ``foundation/llm/streamable.py``), but some
providers and proxies answer with the OpenAI-shaped dict instead
(``{"content": "..."}``).

Callers used to handle that inline, duplicated at each site. That is how
``apps/chat/agent/context_manager.py`` ended up calling ``.get("content")``
on a ``str``: the resulting ``AttributeError`` was swallowed by a broad
``except``, so conversation compaction silently degraded to truncation and
nothing surfaced.

One helper, used by every caller.
"""

from __future__ import annotations

from typing import Any


def as_text(response: Any) -> str:
    """Return the text content of an LLM response.

    Accepts the canonical ``str`` and the dict-shaped
    ``{"content": "..."}`` variant. ``None`` becomes ``""``; anything else
    is coerced with ``str()``.

    Args:
        response: Whatever the LLM client returned.

    Returns:
        The response text, never ``None``.
    """
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content", "")
        return content if isinstance(content, str) else str(content)
    return "" if response is None else str(response)


__all__ = ["as_text"]
