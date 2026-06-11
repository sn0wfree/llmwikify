"""Tests for token-aware message truncation."""

from __future__ import annotations

from unittest.mock import MagicMock
from llmwikify.apps.chat.agent.service import ChatService


def _make_service(context_window: int = 128_000) -> ChatService:
    """Create a ChatService with mocked deps for truncation testing."""
    svc = MagicMock(spec=ChatService)
    svc._chat_config = {
        "max_messages": 5,
        "context_reserve_tokens": 4096,
        "context_window_override": 0,
        "observation_limit": 10,
        "observation_summary_limit": 5,
    }
    # Mock LLM client with budget checker
    llm = MagicMock()
    llm.model = "gpt-4o"
    llm._budget_checker.config.context_window = context_window
    svc.llm_client = llm
    # Bind the real method
    svc._truncate_messages = ChatService._truncate_messages.__get__(svc)
    return svc


class TestTokenAwareTruncation:
    def test_short_messages_not_truncated(self):
        svc = _make_service()
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(3)]
        result = svc._truncate_messages(msgs)
        assert len(result) == len(msgs)

    def test_long_messages_truncated_by_tokens(self):
        svc = _make_service(context_window=1000)
        msgs = [{"role": "system", "content": "You are helpful"}]
        # Each message ~300 chars = ~100 tokens
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(20)]
        result = svc._truncate_messages(msgs)
        assert result[0]["role"] == "system"
        # Should have fewer messages than input
        assert len(result) < len(msgs)
        # Should have a note about dropped messages
        if len(result) > 1:
            assert "omitted" in result[1].get("content", "") or result[1]["role"] == "user"

    def test_system_prompt_always_preserved(self):
        svc = _make_service(context_window=500)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = svc._truncate_messages(msgs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful"

    def test_fallback_to_count_when_no_tokens_fit(self):
        svc = _make_service(context_window=100)
        msgs = [{"role": "system", "content": "x" * 300}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = svc._truncate_messages(msgs)
        # Should still return at least the system prompt
        assert len(result) >= 1
        assert result[0]["role"] == "system"

    def test_empty_messages(self):
        svc = _make_service()
        result = svc._truncate_messages([])
        assert result == []

    def test_single_system_message(self):
        svc = _make_service()
        msgs = [{"role": "system", "content": "hello"}]
        result = svc._truncate_messages(msgs)
        assert result == msgs

    def test_override_context_window(self):
        svc = _make_service(context_window=128_000)
        svc._chat_config["context_window_override"] = 2000
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = svc._truncate_messages(msgs)
        assert result[0]["role"] == "system"
        # Should truncate because override is small
        assert len(result) < len(msgs)
