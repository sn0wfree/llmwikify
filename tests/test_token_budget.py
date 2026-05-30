"""Unit tests for llmwikify.llm module — token estimation, budget checking, context windows."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.llm import (
    CONTEXT_WINDOWS,
    TokenBudgetChecker,
    TokenBudgetConfig,
    TokenBudgetExceeded,
    TokenUsage,
    ask_llm_context_window,
    count_messages,
    count_tokens,
    probe_provider_api,
    resolve_context_window,
)
from llmwikify.llm.context_windows import _extract_ctx_from_name
from llmwikify.llm.token_estimator import _get_tiktoken_encoding


# ─── context_windows.py ─────────────────────────────────────────────


class TestExtractCtxFromName:
    def test_extracts_8k(self):
        assert _extract_ctx_from_name("llama3-8k") == 8192

    def test_extracts_32k(self):
        assert _extract_ctx_from_name("model-32K") == 32768

    def test_extracts_128k(self):
        assert _extract_ctx_from_name("qwen2.5-128k") == 131072

    def test_returns_none_for_no_match(self):
        assert _extract_ctx_from_name("gpt-4o") is None

    def test_returns_none_for_plain_name(self):
        assert _extract_ctx_from_name("llama3") is None


class TestProbeProviderApi:
    def test_returns_context_length(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"context_length": 8192}
        with patch("requests.get", return_value=mock_resp):
            result = probe_provider_api("model", "http://localhost:8000", "key")
            assert result == 8192

    def test_returns_max_model_len(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"max_model_len": 32768}
        with patch("requests.get", return_value=mock_resp):
            result = probe_provider_api("model", "http://localhost:8000", "key")
            assert result == 32768

    def test_returns_none_on_failure(self):
        mock_resp = MagicMock()
        mock_resp.ok = False
        with patch("requests.get", return_value=mock_resp):
            result = probe_provider_api("model", "http://localhost:8000", "key")
            assert result is None

    def test_returns_none_on_exception(self):
        with patch("requests.get", side_effect=ConnectionError("fail")):
            result = probe_provider_api("model", "http://localhost:8000", "key")
            assert result is None


class TestAskLlmContextWindow:
    def test_parses_number_from_response(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "8192"
        result = ask_llm_context_window(mock_client)
        assert result == 8192

    def test_parses_number_with_text(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "My context window is 32768 tokens."
        result = ask_llm_context_window(mock_client)
        assert result == 32768

    def test_returns_none_on_non_numeric(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "I don't know"
        result = ask_llm_context_window(mock_client)
        assert result is None

    def test_returns_none_on_exception(self):
        mock_client = MagicMock()
        mock_client.chat.side_effect = ConnectionError("fail")
        result = ask_llm_context_window(mock_client)
        assert result is None


class TestResolveContextWindow:
    def test_config_override_takes_priority(self):
        result = resolve_context_window("gpt-4o", config_override=99999)
        assert result == 99999

    def test_uses_lookup_table(self):
        result = resolve_context_window("gpt-4o")
        assert result == 128_000

    def test_uses_model_name_inference(self):
        result = resolve_context_window("mymodel-16k")
        assert result == 16384

    def test_uses_default_for_unknown(self):
        result = resolve_context_window("unknown-model")
        assert result == CONTEXT_WINDOWS["default"]

    def test_provider_api_probe(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"max_model_len": 65536}
        with patch("requests.get", return_value=mock_resp):
            result = resolve_context_window(
                "custom-model", base_url="http://localhost:8000", api_key="key"
            )
            assert result == 65536

    def test_debug_asks_llm(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "4096"
        result = resolve_context_window(
            "unknown-model", llm_client=mock_client, debug=True
        )
        assert result == 4096

    def test_debug_not_used_by_default(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "4096"
        result = resolve_context_window("unknown-model", llm_client=mock_client)
        # Should NOT ask LLM (debug=False by default), so falls back to default
        assert result == CONTEXT_WINDOWS["default"]
        mock_client.chat.assert_not_called()


# ─── token_estimator.py ─────────────────────────────────────────────


class TestTokenEstimator:
    def test_count_tokens_empty(self):
        assert count_tokens("") == 0

    def test_count_tokens_english(self):
        # "hello world" should be ~2 tokens with tiktoken
        n = count_tokens("hello world", model="gpt-4o")
        assert 1 <= n <= 5

    def test_count_tokens_chinese(self):
        n = count_tokens("你好世界", model="gpt-4o")
        assert n > 0

    def test_count_tokens_fallback_no_tiktoken(self):
        with patch("llmwikify.llm.token_estimator._get_tiktoken_encoding", return_value=None):
            n = count_tokens("hello world")
            # fallback: len("hello world") // 3 = 11 // 3 = 3
            assert n == 3

    def test_count_tokens_long_text(self):
        text = "word " * 1000  # 5000 chars
        n = count_tokens(text, model="gpt-4o")
        assert n > 100

    def test_count_messages_basic(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        n = count_messages(messages, model="gpt-4o")
        # Each message has 4 overhead + content tokens
        assert n > 8  # at least 2 * 4 overhead

    def test_count_messages_empty_content(self):
        messages = [{"role": "user", "content": ""}]
        n = count_messages(messages, model="gpt-4o")
        assert n >= 4  # at least overhead

    def test_count_messages_multipart_content(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "World"},
                ],
            }
        ]
        n = count_messages(messages, model="gpt-4o")
        assert n > 4

    def test_tiktoken_encoding_caching(self):
        enc1 = _get_tiktoken_encoding("gpt-4o")
        enc2 = _get_tiktoken_encoding("gpt-4o")
        assert enc1 is enc2  # same cached object

    def test_tiktoken_encoding_unknown_model(self):
        enc = _get_tiktoken_encoding("nonexistent-model-xyz")
        assert enc is None


# ─── token_budget.py ────────────────────────────────────────────────


class TestTokenBudgetChecker:
    def test_within_budget(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        messages = [{"role": "user", "content": "Hello"}]
        usage = checker.check(messages, prompt_name="test")
        assert usage.exceeds_window is False
        assert usage.estimated_tokens > 0
        assert usage.context_window == 128_000

    def test_exceeds_budget_warn(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(
                model="gpt-4o",
                context_window=100,  # very small
                reserve_output_tokens=10,
                on_exceed="warn",
            )
        )
        messages = [{"role": "user", "content": "x" * 1000}]
        usage = checker.check(messages, prompt_name="test")
        assert usage.exceeds_window is True

    def test_exceeds_budget_raise(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(
                model="gpt-4o",
                context_window=100,
                reserve_output_tokens=10,
                on_exceed="raise",
            )
        )
        messages = [{"role": "user", "content": "x" * 1000}]
        with pytest.raises(TokenBudgetExceeded, match="Token budget exceeded"):
            checker.check(messages, prompt_name="test")

    def test_usage_log_accumulates(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        for _ in range(5):
            checker.check([{"role": "user", "content": "Hi"}], prompt_name="test")
        stats = checker.get_stats()
        assert stats["total_calls"] == 5

    def test_stats_empty(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        stats = checker.get_stats()
        assert stats["total_calls"] == 0

    def test_stats_tracks_exceeded(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(
                model="gpt-4o", context_window=100_000, on_exceed="warn"
            )
        )
        # First call: small content -> OK
        checker.check([{"role": "user", "content": "Hi"}], prompt_name="test")
        # Second call: large content -> exceeds (use mock to avoid slow tiktoken)
        with patch("llmwikify.llm.token_budget.count_messages", return_value=200_000):
            checker.check(
                [{"role": "user", "content": "x" * 1000}], prompt_name="test"
            )
        stats = checker.get_stats()
        assert stats["total_calls"] == 2
        assert stats["exceeded_count"] == 1
        assert stats["exceeded_rate"] == 0.5

    def test_prompt_name_recorded(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        usage = checker.check(
            [{"role": "user", "content": "Hi"}], prompt_name="analyze_source"
        )
        assert usage.prompt_name == "analyze_source"

    def test_message_count_recorded(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        usage = checker.check(messages, prompt_name="test")
        assert usage.message_count == 3

    def test_largest_message_tracked(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        messages = [
            {"role": "system", "content": "short"},
            {"role": "user", "content": "x" * 500},
        ]
        usage = checker.check(messages, prompt_name="test")
        assert usage.largest_message_tokens > 0

    def test_default_config(self):
        checker = TokenBudgetChecker()
        assert checker.model == "gpt-4o"
        assert checker.context_window == 128_000
        assert checker.reserve_output == 4096
        assert checker.on_exceed == "warn"

    def test_timestamp_is_recent(self):
        checker = TokenBudgetChecker(
            TokenBudgetConfig(model="gpt-4o", context_window=128_000)
        )
        before = time.time()
        usage = checker.check([{"role": "user", "content": "Hi"}])
        after = time.time()
        assert before <= usage.timestamp <= after


# ─── Integration: full flow ─────────────────────────────────────────


class TestIntegration:
    def test_full_flow_within_budget(self):
        """Simulate a realistic LLM call within budget."""
        config = TokenBudgetConfig(
            model="gpt-4o",
            context_window=128_000,
            reserve_output_tokens=4096,
            on_exceed="warn",
        )
        checker = TokenBudgetChecker(config)

        messages = [
            {"role": "system", "content": "You are a document analyst."},
            {"role": "user", "content": "Analyze this document: " + "word " * 500},
        ]

        usage = checker.check(messages, prompt_name="analyze_source")
        assert usage.exceeds_window is False
        assert usage.estimated_tokens < checker.budget

        stats = checker.get_stats()
        assert stats["total_calls"] == 1
        assert stats["exceeded_count"] == 0

    def test_full_flow_exceeds_budget(self):
        """Simulate a request that exceeds the context window."""
        config = TokenBudgetConfig(
            model="gpt-4",
            context_window=8_192,
            reserve_output_tokens=4096,
            on_exceed="warn",
        )
        checker = TokenBudgetChecker(config)

        # Mock count_messages to simulate exceeding budget
        with patch("llmwikify.llm.token_budget.count_messages", return_value=10_000):
            messages = [
                {"role": "system", "content": "x" * 1000},
                {"role": "user", "content": "y" * 1000},
            ]

            usage = checker.check(messages, prompt_name="test")
            assert usage.exceeds_window is True
            assert usage.estimated_tokens > checker.budget
