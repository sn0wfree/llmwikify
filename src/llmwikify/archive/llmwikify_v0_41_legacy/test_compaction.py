"""Tests for message compaction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from llmwikify.apps.chat.agent.service import ChatService


def _make_service(
    context_window: int = 128_000,
    compaction_enabled: bool = True,
    compaction_threshold_ratio: float = 0.8,
) -> ChatService:
    svc = MagicMock(spec=ChatService)
    svc._chat_config = {
        "max_messages": 5,
        "context_reserve_tokens": 4096,
        "context_window_override": 0,
        "observation_limit": 10,
        "observation_summary_limit": 5,
        "compaction_enabled": compaction_enabled,
        "compaction_threshold_ratio": compaction_threshold_ratio,
        "compaction_min_messages": 6,
        "compaction_max_tokens": 4000,
    }
    llm = MagicMock()
    llm.model = "gpt-4o"
    llm._budget_checker.context_window = context_window
    svc.llm_client = llm
    svc.wiki_service = MagicMock()
    svc._compact_messages = ChatService._compact_messages.__get__(svc)
    return svc


class TestMessageCompaction:
    def test_below_threshold_no_compaction(self):
        svc = _make_service(context_window=128_000, compaction_threshold_ratio=0.8)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(4)]
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            svc._compact_messages(msgs)
        )
        assert result == msgs  # No change

    def test_disabled_no_compaction(self):
        svc = _make_service(compaction_enabled=False)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            svc._compact_messages(msgs)
        )
        assert result == msgs

    def test_too_few_messages_no_compaction(self):
        svc = _make_service(context_window=1000, compaction_threshold_ratio=0.1)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(3)]
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            svc._compact_messages(msgs)
        )
        assert result == msgs

    def test_compaction_reduces_messages(self):
        svc = _make_service(context_window=2000, compaction_threshold_ratio=0.1)
        # Make messages large enough to trigger compaction
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 500} for _ in range(10)]
        # Mock LLM response
        svc.wiki_service.get_llm.return_value.achat = AsyncMock(
            return_value={"content": "Summary of conversation"}
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            svc._compact_messages(msgs)
        )
        # Should have: system + summary + last 4 messages = 6
        assert len(result) < len(msgs)
        assert result[0]["role"] == "system"
        assert "summary" in result[1]["content"].lower()

    def test_compaction_failure_falls_back(self):
        svc = _make_service(context_window=2000, compaction_threshold_ratio=0.1)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 500} for _ in range(10)]
        svc.wiki_service.get_llm.return_value.achat = AsyncMock(
            side_effect=Exception("LLM error")
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            svc._compact_messages(msgs)
        )
        assert result == msgs  # Falls back to original
