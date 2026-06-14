"""Tests for the LAL resolver, LLMSpec, and from_spec construction paths.

Part of the LLM Access Layer (LAL) — PR 1 (Stage 1: skeleton).
Covers:

  - LLMSpec frozen-ness and helpers (to_client_kwargs, with_model_override)
  - resolve_chat_llm: priority order (env > config > provider default)
  - Provider id aliasing (minimax -> minimax)
  - env:VAR expansion for api_key
  - resolver_enabled() gradient switch
  - LLMClient.from_spec / StreamableLLMClient.from_spec canonical path
  - LLMClient.from_config backward compatibility (gpt-4o default kept for PR 1)
  - StreamableLLMClient.from_config delegation
  - Provider from_config delegation (minimax / xiaomi)
"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError

import pytest

from llmwikify.foundation.llm.resolver import (
    PROVIDER_ALIASES,
    apply_provider_alias,
    resolve_chat_llm,
    resolver_enabled,
)
from llmwikify.foundation.llm.spec import LLMSpec
from llmwikify.foundation.llm.streamable import StreamableLLMClient
from llmwikify.foundation.llm_client import LLMClient

# ─── LLMSpec dataclass ─────────────────────────────────────────────────


class TestLLMSpec:
    def test_basic_construction(self):
        spec = LLMSpec(
            provider="minimax",
            base_url="https://api.minimaxi.com/v1",
            api_key="k",
            model="minimax-M3",
            context_window=128000,
            timeout=120.0,
            reasoning_split=True,
            auth_scheme="bearer",
        )
        assert spec.provider == "minimax"
        assert spec.model == "minimax-M3"
        assert spec.context_window == 128000
        assert spec.timeout == 120.0
        assert spec.reasoning_split is True
        assert spec.auth_scheme == "bearer"
        assert spec.source == "config"
        assert spec.extra_headers == {}

    def test_frozen_rejects_field_assignment(self):
        spec = LLMSpec(
            provider="minimax",
            base_url="u",
            api_key="k",
            model="m",
            context_window=None,
            timeout=120.0,
            reasoning_split=False,
            auth_scheme="bearer",
        )
        with pytest.raises(FrozenInstanceError):
            spec.model = "other-model"  # type: ignore[misc]

    def test_extra_headers_isolated_per_instance(self):
        a = LLMSpec(
            provider="x", base_url="u", api_key="k", model="m",
            context_window=None, timeout=1.0,
            reasoning_split=False, auth_scheme="bearer",
        )
        b = LLMSpec(
            provider="x", base_url="u", api_key="k", model="m",
            context_window=None, timeout=1.0,
            reasoning_split=False, auth_scheme="bearer",
        )
        a.extra_headers["X-Foo"] = "1"
        assert b.extra_headers == {}

    def test_to_client_kwargs(self):
        spec = LLMSpec(
            provider="minimax",
            base_url="https://api.minimaxi.com/v1",
            api_key="k",
            model="minimax-M3",
            context_window=128000,
            timeout=90.0,
            reasoning_split=True,
            auth_scheme="bearer",
        )
        kw = spec.to_client_kwargs()
        assert kw["provider"] == "minimax"
        assert kw["base_url"] == "https://api.minimaxi.com/v1"
        assert kw["api_key"] == "k"
        assert kw["model"] == "minimax-M3"
        assert kw["context_window"] == 128000
        assert kw["request_timeout_seconds"] == 90.0
        assert kw["reasoning_split"] is True
        assert kw["auth_header"] == "bearer"

    def test_with_model_override_changes_model(self):
        spec = LLMSpec(
            provider="minimax", base_url="u", api_key="k", model="minimax-M3",
            context_window=None, timeout=1.0,
            reasoning_split=False, auth_scheme="bearer",
        )
        new_spec = spec.with_model_override("minimax-M2.7")
        assert new_spec.model == "minimax-M2.7"
        assert spec.model == "minimax-M3"  # original unchanged

    def test_with_model_override_same_model_returns_self(self):
        spec = LLMSpec(
            provider="minimax", base_url="u", api_key="k", model="minimax-M3",
            context_window=None, timeout=1.0,
            reasoning_split=False, auth_scheme="bearer",
        )
        assert spec.with_model_override("minimax-M3") is spec


# ─── Provider alias ────────────────────────────────────────────────────


class TestProviderAlias:
    def test_alias_table_contains_minimax(self):
        assert PROVIDER_ALIASES["minimax"] == "minimax"

    def test_apply_provider_alias_known(self):
        assert apply_provider_alias("minimax") == "minimax"

    def test_apply_provider_alias_unknown_passthrough(self):
        assert apply_provider_alias("openai") == "openai"
        assert apply_provider_alias("ollama") == "ollama"


# ─── resolve_chat_llm priority and behavior ────────────────────────────


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    """Strip LLM_* env vars before each test to avoid leakage."""
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestResolveChatLLM:
    def test_empty_config_uses_openai_default(self):
        spec = resolve_chat_llm({})
        assert spec.provider == "openai"
        assert spec.base_url == "https://api.openai.com"
        assert spec.model == "gpt-4o"
        assert spec.api_key == ""
        assert spec.source == "config"

    def test_config_provider_and_model(self):
        spec = resolve_chat_llm({
            "llm": {
                "provider": "minimax",
                "model": "minimax-M3",
                "api_key": "k",
                "base_url": "https://api.minimaxi.com/v1",
            }
        })
        assert spec.provider == "minimax"
        assert spec.model == "minimax-M3"
        assert spec.api_key == "k"
        assert spec.base_url == "https://api.minimaxi.com/v1"
        assert spec.source == "ui"

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("LLM_API_KEY", "env-key")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com")
        spec = resolve_chat_llm({
            "llm": {
                "provider": "minimax",
                "model": "minimax-M3",
                "api_key": "config-key",
                "base_url": "https://api.minimaxi.com/v1",
            }
        })
        assert spec.provider == "openai"
        assert spec.model == "gpt-4o-mini"
        assert spec.api_key == "env-key"
        assert spec.source == "merged"

    def test_env_var_syntax_in_api_key(self, monkeypatch):
        monkeypatch.setenv("MY_LLM_KEY", "expanded-key")
        spec = resolve_chat_llm({"llm": {"api_key": "env:MY_LLM_KEY"}})
        assert spec.api_key == "expanded-key"

    def test_alias_minimax_to_minimax(self):
        spec = resolve_chat_llm({"llm": {"provider": "minimax"}})
        assert spec.provider == "minimax"
        assert spec.base_url == "https://api.minimaxi.com/v1"
        assert spec.model == "minimax-M3"

    def test_provider_default_model_applied(self):
        spec = resolve_chat_llm({"llm": {"provider": "minimax"}})
        assert spec.model == "minimax-M3"

    def test_provider_default_reasoning_split(self):
        minimax_spec = resolve_chat_llm({"llm": {"provider": "minimax"}})
        assert minimax_spec.reasoning_split is True

        openai_spec = resolve_chat_llm({"llm": {"provider": "openai"}})
        assert openai_spec.reasoning_split is False

    def test_provider_default_auth_scheme(self):
        xiaomi_spec = resolve_chat_llm({"llm": {"provider": "xiaomi"}})
        assert xiaomi_spec.auth_scheme == "api-key"

        openai_spec = resolve_chat_llm({"llm": {"provider": "openai"}})
        assert openai_spec.auth_scheme == "bearer"

    def test_timeout_defaults_to_120(self):
        spec = resolve_chat_llm({})
        assert spec.timeout == 120.0

    def test_timeout_from_config(self):
        spec = resolve_chat_llm({"llm": {"timeout": 60}})
        assert spec.timeout == 60.0

    def test_context_window_from_config(self):
        spec = resolve_chat_llm({"llm": {"context_window": 200000}})
        assert spec.context_window == 200000

    def test_context_window_invalid_becomes_none(self):
        spec = resolve_chat_llm({"llm": {"context_window": "garbage"}})
        assert spec.context_window is None

    def test_no_silent_openai_fallback_when_provider_set(self, monkeypatch):
        # When provider is set to something non-openai, we should never
        # silently fall back to openai/gpt-4o.
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        spec = resolve_chat_llm({"llm": {"provider": "minimax"}})
        assert spec.provider == "minimax"
        assert spec.model == "minimax-M3"

    def test_source_merged_when_both_env_and_config(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "x")
        spec = resolve_chat_llm({"llm": {"provider": "openai"}})
        assert spec.source == "merged"

    def test_source_env_when_only_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        spec = resolve_chat_llm({})
        assert spec.source == "env"

    def test_source_config_when_only_config(self):
        spec = resolve_chat_llm({"llm": {"provider": "openai", "model": "gpt-4o"}})
        assert spec.source == "ui"

    def test_extra_headers_passed_through(self):
        spec = resolve_chat_llm({"llm": {"extra_headers": {"X-Foo": "bar"}}})
        assert spec.extra_headers == {"X-Foo": "bar"}


# ─── resolver_enabled gradient switch ──────────────────────────────────


class TestResolverEnabled:
    def test_default_true(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        assert resolver_enabled() is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "no", "off", ""])
    def test_disabled_values(self, monkeypatch, val):
        monkeypatch.setenv("LLM_USE_RESOLVER", val)
        assert resolver_enabled() is False

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("LLM_USE_RESOLVER", "true")
        assert resolver_enabled() is True


# ─── from_spec canonical path ──────────────────────────────────────────


class TestFromSpec:
    def test_llm_client_from_spec_constructs(self):
        spec = LLMSpec(
            provider="minimax",
            base_url="https://api.minimaxi.com/v1",
            api_key="k",
            model="minimax-M3",
            context_window=128000,
            timeout=60.0,
            reasoning_split=False,
            auth_scheme="bearer",
        )
        client = LLMClient.from_spec(spec)
        assert client.provider == "minimax"
        assert client.api_key == "k"
        assert client.model == "minimax-M3"
        assert client.base_url == "https://api.minimaxi.com/v1"
        # 60.0 may be cast to 60; check value not exact type
        assert client.request_timeout_seconds == 60.0
        # context_window is preserved in the budget checker
        assert client._budget_checker.context_window == 128000

    def test_streamable_from_spec_constructs(self):
        spec = LLMSpec(
            provider="xiaomi",
            base_url="https://token-plan-cn.xiaomimimo.com",
            api_key="k",
            model="mimo-v2.5-pro",
            context_window=None,
            timeout=120.0,
            reasoning_split=True,
            auth_scheme="api-key",
        )
        client = StreamableLLMClient.from_spec(spec)
        assert client.provider == "xiaomi"
        assert client.model == "mimo-v2.5-pro"
        assert client.auth_header == "api-key"
        assert client.reasoning_split is True

    def test_llm_client_complete_aliases_chat(self):
        # Verify complete() exists and is callable; full integration is
        # covered by mock tests elsewhere. We just check the symbol.
        assert hasattr(LLMClient, "complete")
        assert hasattr(StreamableLLMClient, "complete")


# ─── LLMClient.from_config backward compatibility (PR 1 contract) ──────


class TestLLMClientFromConfigCompat:
    def test_disabled_raises(self):
        with pytest.raises(ValueError, match="not enabled"):
            LLMClient.from_config({"llm": {"enabled": False}})

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key not configured"):
            LLMClient.from_config({"llm": {"enabled": True}})

    def test_env_api_key_picks_up(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        client = LLMClient.from_config({"llm": {"enabled": True}})
        assert client.api_key == "test-key"

    def test_env_var_syntax(self, monkeypatch):
        monkeypatch.setenv("MY_LLM_KEY", "x")
        client = LLMClient.from_config({
            "llm": {"enabled": True, "api_key": "env:MY_LLM_KEY"}
        })
        assert client.api_key == "x"

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "env-key")
        monkeypatch.setenv("LLM_MODEL", "env-model")
        client = LLMClient.from_config({
            "llm": {
                "enabled": True,
                "api_key": "config-key",
                "model": "config-model",
            }
        })
        assert client.api_key == "env-key"
        assert client.model == "env-model"

    def test_gpt4o_default_kept_for_pr1(self, monkeypatch):
        # PR 1 must NOT remove the historical default. PR 4 will
        # (via the LLM_LEGACY_FALLBACK gradient switch — see
        # test_foundation_llm_lal_errors.py). This test opts into
        # the legacy fallback so the gpt-4o default is still
        # observable for back-compat verification.
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "true")
        client = LLMClient(api_key="k")
        assert client.model == "gpt-4o"

    def test_ollama_default_url(self, monkeypatch):
        # PR 4 default-off fallback: passing provider=ollama without
        # model is still a configuration error. Use legacy fallback
        # to keep the test's intent (verifying the URL default).
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "true")
        client = LLMClient(provider="ollama", api_key="k")
        assert client.base_url == "http://localhost:11434/v1"

    def test_resolver_disabled_falls_back(self, monkeypatch):
        # When the gradient switch is off, from_config must NOT call
        # the resolver; it must use the legacy inline path.
        monkeypatch.setenv("LLM_USE_RESOLVER", "false")
        # Inline path still works as before:
        client = LLMClient.from_config({
            "llm": {"enabled": True, "api_key": "k", "model": "m"}
        })
        assert client.api_key == "k"
        assert client.model == "m"


# ─── StreamableLLMClient.from_config delegation ────────────────────────


class TestStreamableFromConfig:
    def test_from_config_uses_resolver(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        client = StreamableLLMClient.from_config({
            "llm": {
                "provider": "minimax",
                "model": "minimax-M3",
                "api_key": "k",
                "base_url": "https://api.minimaxi.com/v1",
            }
        })
        assert client.provider == "minimax"
        assert client.model == "minimax-M3"
        assert client.api_key == "k"
        assert client.reasoning_split is True

    def test_from_config_aliases_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        client = StreamableLLMClient.from_config({
            "llm": {
                "provider": "minimax",  # legacy id
                "api_key": "k",
            }
        })
        assert client.provider == "minimax"  # aliased to canonical id
        assert client.model == "minimax-M3"

    def test_from_config_legacy_path(self, monkeypatch):
        monkeypatch.setenv("LLM_USE_RESOLVER", "false")
        # Even with resolver off, the legacy defaults are preserved
        # (PR 1 keeps gpt-4o / openai defaults to avoid breaking
        # downstream callers).
        client = StreamableLLMClient.from_config({
            "llm": {"provider": "minimax", "api_key": "k", "model": "m"}
        })
        assert client.provider == "minimax"


# ─── Provider from_config delegation ───────────────────────────────────


class TestProviderFromConfig:
    def test_minimax_provider_uses_resolver(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        from llmwikify.apps.chat.providers.minimax import MiniMaxProvider
        provider = MiniMaxProvider()
        client = provider.from_config({
            "provider": "minimax",
            "api_key": "k",
            "model": "minimax-M3",
            "base_url": "https://api.minimaxi.com/v1",
        })
        assert client.provider == "minimax"
        assert client.api_key == "k"
        assert client.reasoning_split is True

    def test_minimax_provider_aliases_legacy_id(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        from llmwikify.apps.chat.providers.minimax import MiniMaxProvider
        provider = MiniMaxProvider()
        client = provider.from_config({
            "provider": "minimax",  # legacy id, should alias
            "api_key": "k",
        })
        assert client.provider == "minimax"

    def test_minimax_provider_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        from llmwikify.apps.chat.providers.minimax import MiniMaxProvider
        provider = MiniMaxProvider()
        with pytest.raises(ValueError, match="API key not configured"):
            provider.from_config({"provider": "minimax", "api_key": ""})

    def test_xiaomi_provider_uses_resolver(self, monkeypatch):
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        from llmwikify.apps.chat.providers.xiaomi import XiaomiProvider
        provider = XiaomiProvider()
        client = provider.from_config({
            "provider": "xiaomi",
            "api_key": "k",
            "model": "mimo-v2.5-pro",
            "base_url": "https://token-plan-cn.xiaomimimo.com",
        })
        assert client.provider == "xiaomi"
        assert client.api_key == "k"
        assert client.auth_header == "api-key"
        assert client.reasoning_split is True

    def test_xiaomi_provider_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        from llmwikify.apps.chat.providers.xiaomi import XiaomiProvider
        provider = XiaomiProvider()
        with pytest.raises(ValueError, match="API key not configured"):
            provider.from_config({"provider": "xiaomi", "api_key": ""})

    def test_registry_create_llm_unaffected(self, monkeypatch):
        # Sanity check: the registry still works end-to-end.
        monkeypatch.delenv("LLM_USE_RESOLVER", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "k")
        from llmwikify.apps.chat.providers.registry import create_llm
        client = create_llm({
            "enabled": True,
            "provider": "minimax",
            "model": "minimax-M3",
        })
        assert client.provider == "minimax"
        assert client.api_key == "k"


# ─── Public re-exports ────────────────────────────────────────────────


class TestReExports:
    def test_spec_re_exported(self):
        from llmwikify.foundation.llm import LLMSpec as ReSpec
        assert ReSpec is LLMSpec

    def test_resolver_re_exported(self):
        from llmwikify.foundation.llm import resolve_chat_llm as ReResolve
        assert ReResolve is resolve_chat_llm

    def test_resolver_enabled_re_exported(self):
        from llmwikify.foundation.llm import resolver_enabled as ReEnabled
        assert ReEnabled is resolver_enabled
