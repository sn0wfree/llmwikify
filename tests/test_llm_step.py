"""Tests for the unified LLM call layer (autoresearch.llm_step).

Covers:
- run_prompt resolves the right LLM client per spec.llm_role
- run_prompt calls client.chat() once for each of the 7 steps
- run_prompt returns parsed JSON for expects_json steps and raw text
  for non-JSON steps
- run_prompt injects the framework block when framework_kind is set
  AND six_step_context is provided
- run_prompt does NOT inject when framework_kind is None
- run_prompt's LLMRetryManager fails fast on non-retriable errors
  (e.g. JSON parse) and uses fallback
- run_prompt's LLMRetryManager retries on transient errors
  (e.g. timeout, 503) and uses fallback after exhaustion
- run_prompt re-raises when spec.fallback is None (report/revise)
- run_prompt re-raises KeyError on unknown prompt name
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.autoresearch.llm_step import _resolve_llm_client, run_prompt


# Patch PromptRegistry.get_messages to return a minimal valid message
# list for any prompt name. The actual YAMLs are out of scope for the
# call-layer tests; we only care about client resolution, framework
# injection, retry, and fallback behavior here.
@pytest.fixture(autouse=True)
def _mock_prompt_registry():
    with patch(
        "llmwikify.core.prompt_registry.PromptRegistry.get_messages",
        return_value=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
        ],
    ):
        yield


# ─── helpers ──────────────────────────────────────────────────────────


def _make_ctx(default_llm=None, planning_llm=None, report_llm=None, config=None):
    """Build a minimal ActionContext-like object for run_prompt."""
    ctx = MagicMock()
    ctx.default_llm = default_llm or MagicMock(name="default_llm")
    ctx.planning_llm = planning_llm or MagicMock(name="planning_llm")
    ctx.report_llm = report_llm or MagicMock(name="report_llm")
    ctx.config = config or {}
    return ctx


def _make_llm(chat_return: str):
    """Build a mock LLM whose .chat() returns the given string."""
    llm = MagicMock()
    llm.chat = MagicMock(return_value=chat_return)
    llm.provider = "openai"
    return llm


def _run(coro):
    """Run a coroutine in a fresh event loop (sync helper for pytest)."""
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else asyncio.new_event_loop().run_until_complete(coro)


# ─── client resolution ────────────────────────────────────────────────


class TestResolveLLMClient:
    def test_default_role_uses_default_llm(self):
        ctx = _make_ctx()
        client = _resolve_llm_client(ctx, "default")
        assert client is ctx.default_llm

    def test_planning_role_uses_planning_llm(self):
        ctx = _make_ctx()
        client = _resolve_llm_client(ctx, "planning")
        assert client is ctx.planning_llm

    def test_report_role_uses_report_llm(self):
        ctx = _make_ctx()
        client = _resolve_llm_client(ctx, "report")
        assert client is ctx.report_llm

    def test_planning_falls_back_to_default_if_none(self):
        ctx = _make_ctx()
        ctx.planning_llm = None
        client = _resolve_llm_client(ctx, "planning")
        assert client is ctx.default_llm

    def test_report_falls_back_to_default_if_none(self):
        ctx = _make_ctx()
        ctx.report_llm = None
        client = _resolve_llm_client(ctx, "report")
        assert client is ctx.default_llm


# ─── run_prompt: basic per-step behavior ──────────────────────────────


class TestRunPromptUnified:
    def test_clarify_uses_planning_llm_and_parses_json(self):
        llm = _make_llm(json.dumps({"context": "C", "scope_check": True}))
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })

        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(ctx, "research_clarify", query="my topic")
        )
        # Used planning_llm
        assert llm.chat.called
        # Parsed JSON
        assert result == {"context": "C", "scope_check": True}

    def test_plan_uses_planning_llm(self):
        llm = _make_llm(json.dumps([{"query": "q1", "source_type": "web", "url": ""}]))
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(ctx, "research_plan", query="q")
        )
        assert llm.chat.called
        assert isinstance(result, list)
        assert result[0]["query"] == "q1"

    def test_reason_uses_default_llm(self):
        llm = _make_llm(json.dumps({"thought": "t", "action": "done"}))
        ctx = _make_ctx(default_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_reason",
                query="q", round=0, phase="starting", quality_score=0,
                budget_remaining=1.0, sub_queries_count=0, failed_sq=0,
                sources_count=0, analyzed_count=0, report_exists=False,
                review_exists=False, observations_text="(none)",
            )
        )
        # Used default_llm
        assert llm.chat.called
        assert result == {"thought": "t", "action": "done"}

    def test_report_returns_raw_markdown(self):
        llm = _make_llm("# My Report\n\nSome text")
        ctx = _make_ctx(report_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_report",
                query="q", source_contents="", synthesis="",
            )
        )
        # Raw markdown, not parsed
        assert result == "# My Report\n\nSome text"

    def test_revise_returns_raw_markdown(self):
        llm = _make_llm("# Revised\n\nFixed")
        ctx = _make_ctx(report_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_revise",
                issues_text="- fix typos", source_refs="", report="old",
            )
        )
        assert result == "# Revised\n\nFixed"

    def test_review_parses_json(self):
        llm = _make_llm(json.dumps({
            "approved": True, "score": 8, "feedback": "good", "issues": []
        }))
        ctx = _make_ctx(default_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_review",
                query="q", report="r", source_count=3,
            )
        )
        assert result["approved"] is True
        assert result["score"] == 8


# ─── run_prompt: framework augmentation ───────────────────────────────


class TestFrameworkAugmentation:
    def test_report_injects_framework_block(self):
        llm = _make_llm("# Report")
        ctx = _make_ctx(report_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        six_step_context = {
            "clarification": {"context": "C", "boundaries": "B", "position": "P", "premises": []},
            "evidence_scores": {"src1": 0.9},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.75},
        }
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_report",
                six_step_context=six_step_context,
                query="q", source_contents="", synthesis="",
            )
        )
        # Inspect the messages that were sent
        messages = llm.chat.call_args[0][0]
        # First message should be the framework block
        assert messages[0]["role"] == "system"
        assert "6-step Framework Guidance" in messages[0]["content"]
        # Subsequent messages come from the YAML
        assert len(messages) >= 2

    def test_review_injects_framework_block(self):
        llm = _make_llm(json.dumps({"approved": True, "score": 8}))
        ctx = _make_ctx(default_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        six_step_context = {
            "clarification": {"context": "C"},
            "evidence_scores": {"src1": 0.9},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.75},
        }
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_review",
                six_step_context=six_step_context,
                query="q", report="r", source_count=3,
            )
        )
        messages = llm.chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "6-step Framework Review Checklist" in messages[0]["content"]

    def test_report_no_block_when_context_is_none(self):
        llm = _make_llm("# Report")
        ctx = _make_ctx(report_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_report",
                six_step_context=None,
                query="q", source_contents="", synthesis="",
            )
        )
        messages = llm.chat.call_args[0][0]
        # No framework block injected
        assert not any(
            "6-step Framework Guidance" in m.get("content", "")
            for m in messages
        )

    def test_clarify_does_not_inject_framework_block(self):
        """clarify has framework_kind=None, so no injection regardless of ctx."""
        llm = _make_llm(json.dumps({"context": "C", "scope_check": True}))
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        })
        six_step_context = {
            "clarification": {"context": "C"},
            "evidence_scores": {"src1": 0.9},
        }
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_clarify",
                six_step_context=six_step_context,
                query="q",
            )
        )
        messages = llm.chat.call_args[0][0]
        assert not any(
            "Framework Guidance" in m.get("content", "")
            or "Framework Review Checklist" in m.get("content", "")
            for m in messages
        )


# ─── run_prompt: retry + fallback behavior ────────────────────────────


class TestRunPromptRetryAndFallback:
    def test_reraises_on_json_parse_error(self):
        """Non-retriable error (JSON decode) → no retry → re-raises."""
        llm = MagicMock()
        llm.chat = MagicMock(return_value="not valid json {{")
        llm.provider = "openai"
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 3, "llm_call_timeout_seconds": 30,
        })
        with pytest.raises(Exception, match="Expecting"):
            asyncio.new_event_loop().run_until_complete(
                run_prompt(ctx, "research_clarify", query="q")
            )
        # Called once (no retry on non-retriable)
        assert llm.chat.call_count == 1

    def test_retries_3x_on_transient_error_then_raises(self):
        """Retriable error → retried 3x → re-raises."""
        llm = MagicMock()
        llm.chat = MagicMock(side_effect=Exception("503 service unavailable"))
        llm.provider = "openai"
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 3, "llm_retry_base_delay": 0.001,
            "llm_call_timeout_seconds": 30,
        })
        with pytest.raises(Exception, match="503"):
            asyncio.new_event_loop().run_until_complete(
                run_prompt(ctx, "research_clarify", query="q")
            )
        # Called 3 times (3 attempts)
        assert llm.chat.call_count == 3

    def test_no_fallback_reraises_for_report(self):
        """report has no fallback → re-raises after retries."""
        llm = MagicMock()
        llm.chat = MagicMock(side_effect=Exception("500 internal server error"))
        llm.provider = "openai"
        ctx = _make_ctx(report_llm=llm, config={
            "max_retry_attempts": 2, "llm_retry_base_delay": 0.001,
            "llm_call_timeout_seconds": 30,
        })
        with pytest.raises(Exception, match="500"):
            asyncio.new_event_loop().run_until_complete(
                run_prompt(
                    ctx, "research_report",
                    query="q", source_contents="", synthesis="",
                )
            )
        assert llm.chat.call_count == 2

    def test_unknown_prompt_raises_keyerror(self):
        ctx = _make_ctx()
        with pytest.raises(KeyError):
            asyncio.new_event_loop().run_until_complete(
                run_prompt(ctx, "research_bogus", query="q")
            )

    def test_succeeds_on_second_attempt(self):
        """First call transient-fails, second succeeds → returns real result."""
        llm = MagicMock()
        llm.chat = MagicMock(side_effect=[
            Exception("503 service unavailable"),
            json.dumps({"context": "C", "scope_check": True}),
        ])
        llm.provider = "openai"
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 3, "llm_retry_base_delay": 0.001,
            "llm_call_timeout_seconds": 30,
        })
        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(ctx, "research_clarify", query="q")
        )
        assert llm.chat.call_count == 2
        assert result == {"context": "C", "scope_check": True}
        # Real result, not fallback
        assert "fallback" not in result

    def test_caller_can_use_spec_fallback(self):
        """Caller (not run_prompt) is responsible for invoking spec.fallback."""
        from llmwikify.autoresearch.prompts import PROMPT_REGISTRY

        llm = MagicMock()
        llm.chat = MagicMock(side_effect=Exception("503 service unavailable"))
        llm.provider = "openai"
        ctx = _make_ctx(planning_llm=llm, config={
            "max_retry_attempts": 3, "llm_retry_base_delay": 0.001,
            "llm_call_timeout_seconds": 30,
        })
        try:
            asyncio.new_event_loop().run_until_complete(
                run_prompt(ctx, "research_clarify", query="q")
            )
        except Exception as e:
            # Caller invokes fallback explicitly
            result = PROMPT_REGISTRY["research_clarify"].fallback(query="q", error=e)
        assert result["fallback"] is True
        assert result["scope_check"] is False
        assert "503" in result["fallback_reason"]
