"""Tests for patterns borrowed from nanobot v0.2.1.

Pattern 1: 429 fine classification (billing/quota vs rate-limit).
Pattern 2: Arrearage response detection (402 + billing tokens).
Pattern 3: Thinking style map (reasoning_split / thinking_type / enable_thinking).
Pattern 4: Role alternation hardening (trailing assistant + bare-assistant guard).

Refs:
    docs/poc/m1-research.md
    docs/poc/m1-decision.md
    nanobot v0.2.1 providers/base.py:374-463
    nanobot v0.2.1 providers/openai_compat_provider.py:73-77
"""

from __future__ import annotations

import pytest

from llmwikify.foundation.llm.streamable import (
    _enforce_role_alternation,
    _extract_error_type_code,
    _is_retryable_429_text,
    _normalize_error_token,
    _validate_request,
    build_thinking_extra_body,
    is_arrearage_response,
)


class TestIsRetryable429Text:
    """Pattern 1: distinguish retryable 429 from billing/quota 429."""

    def test_billing_token_returns_false(self):
        """insufficient_quota / payment_required should NOT be retried."""
        assert _is_retryable_429_text("insufficient_quota: please top up") is False
        assert _is_retryable_429_text("Error: payment_required") is False
        assert _is_retryable_429_text("quota exceeded for this account") is False
        assert _is_retryable_429_text("billing hard limit reached") is False
        assert _is_retryable_429_text("out of credits") is False

    def test_rate_limit_returns_true(self):
        """rate_limit / too_many_requests / retry-after SHOULD be retried."""
        assert _is_retryable_429_text("rate limit exceeded, retry after 30s") is True
        assert _is_retryable_429_text("too many requests") is True
        assert _is_retryable_429_text("overloaded, try again in 5 seconds") is True
        assert _is_retryable_429_text("速率限制") is True

    def test_unknown_body_defaults_to_retry(self):
        """Unknown 429 → wait + retry (matches nanobot's default)."""
        assert _is_retryable_429_text("") is True
        assert _is_retryable_429_text(None) is True
        assert _is_retryable_429_text("something weird happened") is True


class TestIsArrearageResponse:
    """Pattern 2: detect billing/quota errors that won't clear on retry."""

    def test_402_is_arrearage(self):
        assert is_arrearage_response(402, "anything") is True
        assert is_arrearage_response(402, None) is True

    def test_billing_text_is_arrearage(self):
        assert is_arrearage_response(429, "insufficient_quota") is True
        assert is_arrearage_response(429, "Your account is out of credits") is True
        assert is_arrearage_response(500, "quota exhausted") is True

    def test_rate_limit_text_is_not_arrearage(self):
        assert is_arrearage_response(429, "rate limit exceeded") is False
        assert is_arrearage_response(429, None) is False

    def test_4xx_other_codes_with_billing_text(self):
        """402 OR billing tokens trigger arrearage; status alone is not enough."""
        assert is_arrearage_response(401, "insufficient_quota") is True
        assert is_arrearage_response(400, "payment required") is True


class TestBuildThinkingExtraBody:
    """Pattern 3: provider-native thinking toggles via style map."""

    def test_reasoning_split_style(self):
        """MiniMax uses reasoning_split bool."""
        assert build_thinking_extra_body("reasoning_split", True) == {"reasoning_split": True}
        assert build_thinking_extra_body("reasoning_split", False) == {"reasoning_split": False}

    def test_thinking_type_style(self):
        """DeepSeek / VolcEngine / Xiaomi MiMo use thinking.type."""
        assert build_thinking_extra_body("thinking_type", True) == {
            "thinking": {"type": "enabled"}
        }
        assert build_thinking_extra_body("thinking_type", False) == {
            "thinking": {"type": "disabled"}
        }

    def test_enable_thinking_style(self):
        """DashScope / Qwen use enable_thinking bool."""
        assert build_thinking_extra_body("enable_thinking", True) == {"enable_thinking": True}
        assert build_thinking_extra_body("enable_thinking", False) == {"enable_thinking": False}

    def test_unknown_style_returns_none(self):
        """Empty / unknown style returns None (no extra_body fragment)."""
        assert build_thinking_extra_body("", True) is None
        assert build_thinking_extra_body("nonexistent", True) is None


class TestEnforceRoleAlternation:
    """Pattern 4: normalize role alternation for OpenAI-compatible APIs."""

    def test_trailing_assistant_dropped(self):
        """Trailing assistant messages are dropped (no prefill support).

        nanobot behavior: after merging consecutive same-role msgs,
        the trailing assistant is ALWAYS popped (even if it has
        tool_calls). For llmwikify, this means the chat flow loses
        any pending tool-call context. Document the behavior; revisit
        if it conflicts with the wiki tool dispatch flow.
        """
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = _enforce_role_alternation(msgs)
        # Trailing assistant is popped regardless of merge outcome.
        assert [m["role"] for m in result] == ["user"]

    def test_trailing_assistant_recovered_as_user_when_only_system_left(self):
        """If dropping leaves only system msgs, promote last popped → user."""
        msgs = [
            {"role": "system", "content": "you are helpful"},
            {"role": "assistant", "content": "previous answer"},
        ]
        result = _enforce_role_alternation(msgs)
        # Last popped is promoted to user so the LLM can still see it.
        assert [m["role"] for m in result] == ["system", "user"]
        assert result[-1]["content"] == "previous answer"

    def test_bare_assistant_first_gets_synthetic_user(self):
        """If only system + bare assistant remain, recovery promotes to user."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "prefill"},
        ]
        result = _enforce_role_alternation(msgs)
        # Trailing assistant popped, then recovered as user (not synthetic).
        assert [m["role"] for m in result] == ["system", "user"]
        assert result[-1]["content"] == "prefill"

    def test_synthetic_user_not_inserted_when_user_msgs_present(self):
        """Synthetic user NOT inserted when user msgs already exist."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "prefill"},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": "trailing"},
        ]
        result = _enforce_role_alternation(msgs)
        # Trailing assistant popped; user msgs left, so no recovery.
        assert [m["role"] for m in result] == ["system", "user", "assistant", "user"]

    def test_consecutive_user_messages_merged(self):
        """Consecutive user messages get their content concatenated."""
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        result = _enforce_role_alternation(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "first\n\nsecond"

    def test_empty_messages_unchanged(self):
        assert _enforce_role_alternation([]) == []

    def test_tool_call_message_dropped_if_no_tool_response(self):
        """Trailing assistant with tool_calls is dropped (nanobot behavior).

        This is potentially lossy: the LLM loses its own tool-call
        request. We match nanobot here for behavioral parity; revisit
        if llmwikify's wiki tool dispatch needs different semantics.
        """
        msgs = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "1", "function": {"name": "foo"}}],
                "content": None,
            },
        ]
        result = _enforce_role_alternation(msgs)
        assert [m["role"] for m in result] == ["user"]


class TestNormalizeErrorToken:
    """Helper for token extraction in _extract_error_type_code."""

    def test_none_returns_none(self):
        assert _normalize_error_token(None) is None

    def test_empty_string_returns_none(self):
        assert _normalize_error_token("") is None
        assert _normalize_error_token("   ") is None

    def test_lowercases_and_strips(self):
        assert _normalize_error_token("  InSufficient_Quota  ") == "insufficient_quota"

    def test_non_string_value_stringified(self):
        assert _normalize_error_token(429) == "429"
        assert _normalize_error_token(False) == "false"


class TestExtractErrorTypeCode:
    """Helper for parsing error payload into (type, code) tuple."""

    def test_dict_input(self):
        assert _extract_error_type_code({"type": "rate_limit_error", "code": "x"}) == (
            "rate_limit_error",
            "x",
        )

    def test_dict_with_nested_error(self):
        payload = {"error": {"type": "insufficient_quota", "code": "quota"}}
        assert _extract_error_type_code(payload) == ("insufficient_quota", "quota")

    def test_json_string_input(self):
        assert _extract_error_type_code('{"type": "rate_limit_error"}') == (
            "rate_limit_error",
            None,
        )

    def test_non_json_string_returns_nones(self):
        assert _extract_error_type_code("not json") == (None, None)

    def test_non_dict_returns_nones(self):
        assert _extract_error_type_code(42) == (None, None)
        assert _extract_error_type_code(None) == (None, None)


class TestValidateRequestIntegratesRoleAlternation:
    """Verify _validate_request mutates messages via _enforce_role_alternation."""

    def test_trailing_assistant_cleaned_by_validate(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "trailing"},
        ]
        _validate_request(msgs)
        # Trailing assistant dropped; list mutated in-place.
        assert [m["role"] for m in msgs] == ["user"]
