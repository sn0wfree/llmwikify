"""Unit tests for ContextManager + AgentContext.

Migrated from archive/llmwikify_v0_41_legacy/test_apps_chat_agent_service.py
(TestAgentContext) + test_compaction.py + test_token_truncation.py.

After B-7 refactor (98a47bd), the v0.41 ChatService was replaced by:
  - apps/chat/agent/context_manager.py: AgentContext + ContextManager
                                       (.compact() / .truncate() / .get_or_create())
  - apps/chat/agent/orchestrator.py:    main chat loop
  - apps/chat/agent/runner_v2.py:       ChatRunnerV2 (microcompact)

These tests verify the standalone unit-test surface of the new
ContextManager class, mirroring the v0.41 archive tests but with the
new API (ContextManager instance methods vs ChatService private methods).

Coverage:
  - TestAgentContext: 5 cases (state mgmt, copy semantics)
  - TestCompaction:   5 cases (disabled / too-few / below-threshold / reduces / fail-fallback)
  - TestTruncation:   7 cases (short / long / system-preserved / fallback / empty / single / override)

Target: 17 tests, no real LLM calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.context_manager import (
    AgentContext,
    ContextManager,
)

# ─── AgentContext ────────────────────────────────────────────────


class TestAgentContext:
    def test_init_empty(self) -> None:
        ctx = AgentContext()
        assert ctx.wiki_id is None
        assert ctx.messages == []
        assert ctx.recent_wiki_id is None
        assert ctx._tool_calls == {}

    def test_add_user_message(self) -> None:
        ctx = AgentContext()
        ctx.add_user_message("hello")
        assert ctx.messages == [{"role": "user", "content": "hello"}]

    def test_add_assistant_message(self) -> None:
        ctx = AgentContext()
        ctx.add_assistant_message("hi")
        assert ctx.messages == [{"role": "assistant", "content": "hi"}]

    def test_get_messages_returns_copy(self) -> None:
        ctx = AgentContext()
        ctx.add_user_message("a")
        msgs = ctx.get_messages()
        msgs.append({"role": "user", "content": "b"})
        # Original should be unchanged (copy semantics)
        assert len(ctx.messages) == 1

    def test_set_recent_wiki(self) -> None:
        ctx = AgentContext()
        ctx.set_recent_wiki("my_wiki")
        assert ctx.recent_wiki_id == "my_wiki"


# ─── Compaction ──────────────────────────────────────────────────


def _make_context_manager(
    compaction_enabled: bool = True,
    compaction_threshold_ratio: float = 0.8,
    compaction_min_messages: int = 6,
    context_window: int = 128_000,
) -> ContextManager:
    """Build a ContextManager with mocked LLM and chat config."""
    llm = MagicMock()
    llm.model = "gpt-4o"
    llm._budget_checker = MagicMock()
    llm._budget_checker.context_window = context_window
    return ContextManager(
        config={
            "compaction_enabled": compaction_enabled,
            "compaction_threshold_ratio": compaction_threshold_ratio,
            "compaction_min_messages": compaction_min_messages,
            "compaction_max_tokens": 4000,
            "context_reserve_tokens": 4096,
            "context_window_override": 0,
            "observation_limit": 10,
            "observation_summary_limit": 5,
        },
        llm_client=llm,
    )


class TestCompaction:
    @pytest.mark.asyncio
    async def test_below_threshold_no_compaction(self) -> None:
        cm = _make_context_manager(
            context_window=128_000,
            compaction_threshold_ratio=0.8,
        )
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(4)]
        result = await cm.compact(msgs)
        # Tokens way below threshold — no compaction
        assert result == msgs

    @pytest.mark.asyncio
    async def test_disabled_no_compaction(self) -> None:
        cm = _make_context_manager(compaction_enabled=False)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = await cm.compact(msgs)
        # Disabled config short-circuits before LLM call
        assert result == msgs

    @pytest.mark.asyncio
    async def test_too_few_messages_no_compaction(self) -> None:
        cm = _make_context_manager(
            context_window=1000,
            compaction_threshold_ratio=0.1,
            compaction_min_messages=6,
        )
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(3)]
        result = await cm.compact(msgs)
        # Below compaction_min_messages short-circuits
        assert result == msgs

    @pytest.mark.asyncio
    async def test_compaction_reduces_messages(self) -> None:
        cm = _make_context_manager(
            context_window=2000,
            compaction_threshold_ratio=0.1,
        )
        # Large messages to exceed the small threshold
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 500} for _ in range(10)]
        # Mock LLM to return a summary
        cm._llm_client.achat = AsyncMock(
            return_value={"content": "Summary of conversation"},
        )
        result = await cm.compact(msgs)
        # Compacted: system + summary + last 4 = 6 messages
        assert len(result) < len(msgs)
        assert result[0]["role"] == "system"
        assert "summary" in result[1]["content"].lower()

    @pytest.mark.asyncio
    async def test_compaction_failure_falls_back(self) -> None:
        cm = _make_context_manager(
            context_window=2000,
            compaction_threshold_ratio=0.1,
        )
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 500} for _ in range(10)]
        # LLM errors out
        cm._llm_client.achat = AsyncMock(
            side_effect=Exception("LLM error"),
        )
        result = await cm.compact(msgs)
        # Falls back to original messages on exception
        assert result == msgs


# ─── Truncation ──────────────────────────────────────────────────


class TestTruncation:
    def test_short_messages_not_truncated(self) -> None:
        cm = _make_context_manager()
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": f"msg{i}"} for i in range(3)]
        result = cm.truncate(msgs)
        # Short — no drop note needed
        assert len(result) == len(msgs)

    def test_long_messages_truncated_by_tokens(self) -> None:
        cm = _make_context_manager(context_window=1000)
        msgs = [{"role": "system", "content": "You are helpful"}]
        # Each user message ~300 chars = ~100 tokens; budget < total
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(20)]
        result = cm.truncate(msgs)
        assert result[0]["role"] == "system"
        # Should have fewer messages than input
        assert len(result) < len(msgs)

    def test_system_prompt_always_preserved(self) -> None:
        cm = _make_context_manager(context_window=500)
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = cm.truncate(msgs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful"

    def test_fallback_to_count_when_no_tokens_fit(self) -> None:
        cm = _make_context_manager(context_window=100)
        msgs = [{"role": "system", "content": "x" * 300}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = cm.truncate(msgs)
        # System prompt must survive even if everything else dropped
        assert len(result) >= 1
        assert result[0]["role"] == "system"

    def test_empty_messages(self) -> None:
        cm = _make_context_manager()
        result = cm.truncate([])
        assert result == []

    def test_single_system_message(self) -> None:
        cm = _make_context_manager()
        msgs = [{"role": "system", "content": "hello"}]
        result = cm.truncate(msgs)
        assert result == msgs

    def test_override_context_window(self) -> None:
        cm = _make_context_manager(context_window=128_000)
        # Override forces a tight window regardless of LLM budget
        cm.config["context_window_override"] = 2000
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 300} for _ in range(10)]
        result = cm.truncate(msgs)
        assert result[0]["role"] == "system"
        # Override is small — should truncate
        assert len(result) < len(msgs)


# ─── prepare_messages (integration) ──────────────────────────────


class TestPrepareMessages:
    @pytest.mark.asyncio
    async def test_prepare_applies_compact_then_truncate(self) -> None:
        cm = _make_context_manager(
            context_window=2000,
            compaction_threshold_ratio=0.1,
        )
        # Build messages that will trigger compact + truncate
        msgs = [{"role": "system", "content": "You are helpful"}]
        msgs += [{"role": "user", "content": "x" * 500} for _ in range(10)]
        cm._llm_client.achat = AsyncMock(
            return_value={"content": "Compact summary."},
        )
        result = await cm.prepare_messages(msgs, wiki_service=None)
        # First message is system; structure reflects compact+truncate
        assert result[0]["role"] == "system"
        assert len(result) <= len(msgs)


# ─── D-route reload (2026-07-10 fix for MiniMax error 2013) ────
#
# Verifies that ``ContextManager.get_or_create`` reconstructs the
# missing ``role=tool`` messages for every assistant(tool_calls)
# row pulled from the DB. The DB persists
# ``{tool, args, result, call_id, status}`` per assistant message;
# the schema has no ``role=tool`` rows, so on TTL-expiry reload we
# must rebuild them in-memory before sending the next LLM call.


class TestDRouteReload:
    @pytest.mark.asyncio
    async def test_get_or_create_rebuilds_tool_pair_from_db(self) -> None:
        cm = ContextManager(
            config={
                "compaction_enabled": False,
                "context_store_max_size": 100,
                "context_store_ttl_seconds": 1800,
                "context_reserve_tokens": 0,
                "context_window_override": 1_000_000,
            },
        )
        history = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": '[{"tool": "web_search", "args": {"q": "x"},'
                ' "call_id": "call_abc123",'
                ' "result": {"status": "ok", "data": "found"}}]',
            },
        ]
        ctx = await cm.get_or_create(
            session_id="s1",
            wiki_id=None,
            history_loader=AsyncMock(return_value=history),
            db=None,
        )
        assert len(ctx.messages) == 3
        assert ctx.messages[1]["role"] == "assistant"
        assert ctx.messages[1]["tool_calls"][0]["id"] == "call_abc123"
        assert ctx.messages[2]["role"] == "tool"
        assert ctx.messages[2]["tool_call_id"] == "call_abc123"

    @pytest.mark.asyncio
    async def test_get_or_create_generates_id_when_missing(self) -> None:
        cm = ContextManager(
            config={
                "compaction_enabled": False,
                "context_store_max_size": 100,
                "context_store_ttl_seconds": 1800,
                "context_reserve_tokens": 0,
                "context_window_override": 1_000_000,
            },
        )
        history = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": '[{"tool": "calc", "args": {"a": 1},'
                ' "call_id": "", "result": {"r": 42}}]',
            },
        ]
        ctx = await cm.get_or_create(
            session_id="s2",
            wiki_id=None,
            history_loader=AsyncMock(return_value=history),
            db=None,
        )
        # Fallback id is 5-char "call_" + 24 hex chars
        new_id = ctx.messages[0]["tool_calls"][0]["id"]
        assert new_id.startswith("call_")
        assert len(new_id) == 5 + 24
        # And the matching tool message references the same id
        assert ctx.messages[1]["tool_call_id"] == new_id

    @pytest.mark.asyncio
    async def test_get_or_create_skips_tool_when_result_absent(self) -> None:
        """An assistant(tool_calls) with no ``result`` field does NOT
        emit a tool message. This is consistent with the runtime
        helper only persisting results when the tool actually ran."""
        cm = ContextManager(
            config={
                "compaction_enabled": False,
                "context_store_max_size": 100,
                "context_store_ttl_seconds": 1800,
                "context_reserve_tokens": 0,
                "context_window_override": 1_000_000,
            },
        )
        history = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": '[{"tool": "calc", "args": {},'
                ' "call_id": "call_no_result"}]',
            },
        ]
        ctx = await cm.get_or_create(
            session_id="s3",
            wiki_id=None,
            history_loader=AsyncMock(return_value=history),
            db=None,
        )
        # Only the assistant message is rebuilt; no tool message.
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["role"] == "assistant"


class TestTruncationPreciseCallID:
    """When truncation cuts off the assistant+tool_calls declaration
    for a ``role=tool`` message, the recovered assistant MUST be the
    one that actually owns this ``tool_call_id`` (NOT any random
    assistant with tool_calls). This was the source of the MiniMax
    error 2013 cascade observed in session d8a24ecf."""

    def test_truncate_recovers_assistant_with_matching_call_id(self) -> None:
        cm = ContextManager(
            config={
                "compaction_enabled": False,
                "context_store_max_size": 100,
                "context_store_ttl_seconds": 1800,
                "context_reserve_tokens": 0,
                # Tight budget ensures truncation runs.
                "context_window_override": 800,
            },
            llm_client=MagicMock(
                model="gpt-4o",
                _budget_checker=MagicMock(context_window=800),
            ),
        )
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},  # unrelated
            {"role": "user", "content": "u2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "match_me",
                    "type": "function",
                    "function": {"name": "t", "arguments": "{}"},
                }],
            },
            {
                "role": "tool",
                "name": "t",
                "content": "r",
                "tool_call_id": "match_me",
            },
            {"role": "user", "content": "u3"},
        ]
        result = cm.truncate(msgs)
        # Find the tool message in the output
        tool_idx = next(
            (
                i for i, m in enumerate(result)
                if m.get("role") == "tool"
                and m.get("tool_call_id") == "match_me"
            ),
            None,
        )
        assert tool_idx is not None, "tool message dropped entirely"
        # The preceding message in the output MUST be the assistant
        # that owned it (with matching tool_calls) — NOT a random
        # earlier assistant.
        preceding = result[tool_idx - 1]
        assert preceding.get("role") == "assistant"
        assert any(
            tc.get("id") == "match_me"
            for tc in preceding.get("tool_calls", [])
        )
