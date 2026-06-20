"""Minimal mock LLM fixture for chat_e2e tests.

Patches ``StreamableLLMClient.astream_chat`` so the chat endpoint
can run end-to-end without a real LLM provider. Yields
``"Hello from mock LLM!"`` plus the surrounding done marker.

Usage: prepend this directory to ``sys.path`` so ``import mock_llm``
loads before llmwikify wires its real StreamableLLMClient.

This file is intentionally minimal — Phase A-3 fix for LAL
chat_e2e blocker. See ``tests/test_chat_e2e.py`` for the e2e
flows it underpins.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

_MOCK_CONTENT = "Hello from mock LLM!"


async def _mock_astream_chat(
    self: Any,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | None = None,
    **generation_params: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Yield a single content chunk followed by done.

    The shape mirrors what ``StreamableLLMClient.astream_chat`` is
    expected to emit (``{"type": "content", "text": ...}`` /
    ``{"type": "done", "content": ...}``).
    """
    yield {"type": "content", "text": _MOCK_CONTENT}
    yield {"type": "done", "content": _MOCK_CONTENT}


def install() -> None:
    """Monkey-patch StreamableLLMClient.astream_chat. Idempotent."""
    try:
        from llmwikify.foundation.llm.streamable import (
            StreamableLLMClient,
        )
    except Exception:
        return
    if getattr(StreamableLLMClient.astream_chat, "_mock_llm_installed", False):
        return
    StreamableLLMClient.astream_chat = _mock_astream_chat  # type: ignore[method-assign]
    StreamableLLMClient.astream_chat._mock_llm_installed = True  # type: ignore[attr-defined]


install()
