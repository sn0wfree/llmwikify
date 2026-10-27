"""Regression tests for the LLM response contract fix.

``achat`` is declared ``-> str`` (both providers agree on that), but
``apps/chat/agent/context_manager.py`` called ``.get("content")`` on the
result. The ``AttributeError`` was caught by a broad ``except``, so
conversation compaction never ran and always degraded to truncation.

Fix: ``foundation/llm/response.py::as_text()`` normalizes both the
canonical ``str`` and the OpenAI-shaped dict; the three call sites
(``context_manager`` / ``dream`` / ``consolidator``) share it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from llmwikify.apps.chat.agent.context_manager import ContextManager
from llmwikify.foundation.llm.response import as_text


class TestAsText:
    def test_str_passthrough(self) -> None:
        assert as_text("hello") == "hello"

    def test_dict_content(self) -> None:
        assert as_text({"content": "hello"}) == "hello"

    def test_dict_without_content(self) -> None:
        assert as_text({}) == ""

    def test_dict_with_non_str_content(self) -> None:
        assert as_text({"content": 42}) == "42"

    def test_none(self) -> None:
        assert as_text(None) == ""

    def test_other_type_coerced(self) -> None:
        assert as_text(123) == "123"


class TestCompactionUsesResponseCorrectly:
    """`ContextManager.compact` must actually compact, not silently degrade."""

    @staticmethod
    def _manager(client: Any) -> ContextManager:
        return ContextManager(
            config={
                "compaction_enabled": True,
                "compaction_min_messages": 2,
                "compaction_threshold_ratio": 0.0,
                "compaction_max_tokens": 10_000,
                "context_window_override": 1_000,
                "context_reserve_tokens": 0,
            },
            llm_client=client,
        )

    @staticmethod
    def _messages() -> list[dict[str, str]]:
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old 1"},
            {"role": "user", "content": "old 2"},
            {"role": "user", "content": "old 3"},
            {"role": "user", "content": "recent 1"},
            {"role": "user", "content": "recent 2"},
            {"role": "user", "content": "recent 3"},
            {"role": "user", "content": "recent 4"},
        ]

    def test_compact_uses_str_response(self) -> None:
        """A client returning the canonical ``str`` must work."""

        class StrClient:
            def __init__(self) -> None:
                self.calls = 0

            async def achat(self, **kwargs: Any) -> str:
                self.calls += 1
                return "SUMMARY TEXT"

        client = StrClient()
        out = asyncio.run(self._manager(client).compact(self._messages()))
        assert client.calls == 1, "compaction must actually call the LLM"
        assert out[0]["content"] == "sys"
        assert any("SUMMARY TEXT" in m.get("content", "") for m in out)

    def test_compact_accepts_dict_response(self) -> None:
        """A provider answering with the OpenAI-shaped dict must also work."""

        class DictClient:
            async def achat(self, **kwargs: Any) -> dict:
                return {"content": "SUMMARY TEXT"}

        out = asyncio.run(self._manager(DictClient()).compact(self._messages()))
        assert any("SUMMARY TEXT" in m.get("content", "") for m in out)
