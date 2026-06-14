"""Tests for LAL PR 4: failure semantics + legacy fallback removal.

Covers:
  - 4 LAL error types (LLMError / LLMNotConfiguredError /
    LLMModelNotSupportedError / LLMSpecMismatchError /
    SubagentLLMError) and their `action` + `path` fields
  - LLMClient() / StreamableLLMClient() raise
    LLMNotConfiguredError when constructed without provider/model
  - LLM_LEGACY_FALLBACK gradient switch restores old defaults
  - DEFAULT_CONFIG llm fields are None / False
  - All gpt-4o fallbacks are gone (service.py / context_manager.py
    / orchestrator.py); missing model falls back to "unknown"
  - Provider id rename: `minimax` -> `minimax`, with alias
    resolution for back-compat
  - Provider registry resolves legacy id via alias
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmwikify.apps.chat.providers.minimax import MiniMaxProvider
from llmwikify.apps.chat.providers.registry import (
    PROVIDERS,
    create_llm,
    get_provider,
    list_providers,
)
from llmwikify.foundation import config as foundation_config
from llmwikify.foundation.llm import errors as lal_errors
from llmwikify.foundation.llm.errors import (
    LLMError,
    LLMModelNotSupportedError,
    LLMNotConfiguredError,
    LLMSpecMismatchError,
    SubagentLLMError,
)
from llmwikify.foundation.llm.resolver import apply_provider_alias
from llmwikify.foundation.llm.spec import LLMSpec
from llmwikify.foundation.llm.streamable import StreamableLLMClient
from llmwikify.foundation.llm_client import LLMClient, _legacy_fallback_enabled


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("LLM_LEGACY_FALLBACK", "LLM_API_KEY", "LLM_BASE_URL",
              "LLM_MODEL", "LLM_PROVIDER", "LLM_USE_RESOLVER"):
        monkeypatch.delenv(k, raising=False)
    yield


# ─── LAL error types ───────────────────────────────────────────────────


class TestLALErrorTypes:
    def test_llm_error_base(self):
        e = LLMError("boom", action="x", path="/y")
        assert e.action == "x"
        assert e.path == "/y"
        assert e.details == {}

    def test_not_configured(self):
        e = LLMNotConfiguredError("not configured")
        assert e.action == "go-to-llm-settings"
        assert e.path == "/llm-settings"
        assert "not configured" in str(e)

    def test_not_configured_custom_path(self):
        e = LLMNotConfiguredError("x", path="/custom")
        assert e.path == "/custom"

    def test_model_not_supported(self):
        e = LLMModelNotSupportedError(
            "bad model",
            provider="minimax",
            model="gpt-4o",
            supported=["minimax-M3"],
        )
        assert e.action == "select-supported-model"
        assert e.details["provider"] == "minimax"
        assert e.details["model"] == "gpt-4o"
        assert e.details["supported"] == ["minimax-M3"]

    def test_spec_mismatch(self):
        e = LLMSpecMismatchError(
            "mismatch",
            actor="clarifier",
            actor_model="gpt-4o",
            spec_model="minimax-M3",
            provider="minimax",
        )
        assert e.action == "fix-workflow-yaml"
        assert e.details["actor"] == "clarifier"
        assert e.details["actor_model"] == "gpt-4o"

    def test_subagent_llm_error(self):
        e = SubagentLLMError(
            "subagent failed",
            actor="planner",
            original_error="ConnectionError: foo",
        )
        assert e.action == "retry-or-check-provider"
        assert e.details["actor"] == "planner"
        assert "ConnectionError" in e.details["original_error"]

    def test_all_errors_subclass_llm_error(self):
        for cls in (
            LLMNotConfiguredError,
            LLMModelNotSupportedError,
            LLMSpecMismatchError,
            SubagentLLMError,
        ):
            assert issubclass(cls, LLMError)

    def test_all_errors_importable_from_lal_module(self):
        # Re-export check.
        from llmwikify.foundation.llm import errors as m
        assert m.LLMNotConfiguredError is LLMNotConfiguredError
        assert m.LLMModelNotSupportedError is LLMModelNotSupportedError
        assert m.LLMSpecMismatchError is LLMSpecMismatchError
        assert m.SubagentLLMError is SubagentLLMError
        assert m.LLMError is LLMError


# ─── LLMClient/StreamableLLMClient default-raise ───────────────────────


class TestUnconfiguredClientRaises:
    def test_llm_client_no_args_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "false")
        with pytest.raises(LLMNotConfiguredError, match="provider"):
            LLMClient()

    def test_llm_client_no_model_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "false")
        with pytest.raises(LLMNotConfiguredError, match="model"):
            LLMClient(provider="minimax")

    def test_streamable_client_no_args_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "false")
        with pytest.raises(LLMNotConfiguredError, match="provider"):
            StreamableLLMClient()

    def test_streamable_client_no_model_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "false")
        with pytest.raises(LLMNotConfiguredError, match="model"):
            StreamableLLMClient(provider="minimax")

    def test_legacy_fallback_default_off(self, monkeypatch):
        monkeypatch.delenv("LLM_LEGACY_FALLBACK", raising=False)
        assert _legacy_fallback_enabled() is False

    @pytest.mark.parametrize("v", ["true", "True", "1", "yes", "on"])
    def test_legacy_fallback_enabled(self, monkeypatch, v):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", v)
        assert _legacy_fallback_enabled() is True

    def test_legacy_fallback_keeps_old_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "true")
        # Old behaviour: LLMClient() succeeds with openai/gpt-4o.
        client = LLMClient()
        assert client.provider == "openai"
        assert client.model == "gpt-4o"

    def test_explicit_provider_and_model_works(self, monkeypatch):
        monkeypatch.setenv("LLM_LEGACY_FALLBACK", "false")
        client = LLMClient(provider="minimax", api_key="k", model="minimax-M3")
        assert client.provider == "minimax"
        assert client.model == "minimax-M3"


# ─── DEFAULT_CONFIG llm fields ────────────────────────────────────────


class TestDefaultConfigLLM:
    def test_default_llm_enabled_false(self):
        cfg = foundation_config.DEFAULT_CONFIG
        assert cfg["llm"]["enabled"] is False

    def test_default_llm_provider_none(self):
        cfg = foundation_config.DEFAULT_CONFIG
        assert cfg["llm"]["provider"] is None

    def test_default_llm_model_none(self):
        cfg = foundation_config.DEFAULT_CONFIG
        assert cfg["llm"]["model"] is None

    def test_default_llm_base_url_none(self):
        cfg = foundation_config.DEFAULT_CONFIG
        assert cfg["llm"]["base_url"] is None

    def test_no_gpt4_in_defaults(self):
        cfg = foundation_config.DEFAULT_CONFIG
        llm = cfg["llm"]
        assert "gpt-4" not in str(llm)
        assert "openai" not in str(llm).lower() or llm.get("provider") is None


# ─── gpt-4o fallbacks removed from agent code paths ────────────────────


class TestNoGPT4OFallbacks:
    def test_context_manager_no_gpt4o(self, monkeypatch):
        from llmwikify.apps.chat.agent.context_manager import ContextManager
        # Construct without an llm_client; method should NOT
        # return 'gpt-4o' as the model name (PR 4 contract).
        cm = ContextManager.__new__(ContextManager)
        cm._llm_client = None
        assert cm._get_model_name() == "unknown"

    def test_context_manager_uses_real_model_when_set(self, monkeypatch):
        from llmwikify.apps.chat.agent.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        # A bare object with a .model attribute mimics the client.
        class _Fake:
            model = "minimax-M3"
        cm._llm_client = _Fake()
        assert cm._get_model_name() == "minimax-M3"


# ─── Provider id (alias resolution is in place) ────────────────────────


class TestProviderIdResolution:
    def test_minimax_provider_id(self):
        p = MiniMaxProvider()
        # The canonical id is what's returned by provider_name().
        canonical = p.provider_name()
        # It must be a valid id, and alias must be a no-op on it.
        assert apply_provider_alias(canonical) == canonical

    def test_apply_alias_openai_unchanged(self):
        assert apply_provider_alias("openai") == "openai"

    def test_apply_alias_xiaomi_unchanged(self):
        assert apply_provider_alias("xiaomi") == "xiaomi"

    def test_registry_has_minimax(self):
        providers = list_providers()
        assert "minimax" in providers

    def test_registry_resolves_unknown_via_alias_table(self):
        # If a legacy alias exists for a known provider, it must
        # resolve. The alias is in PROVIDER_ALIASES.
        from llmwikify.foundation.llm.resolver import PROVIDER_ALIASES
        # Each alias target must be a registered provider.
        for legacy, canonical in PROVIDER_ALIASES.items():
            assert canonical in PROVIDERS, (
                f"alias {legacy!r} -> {canonical!r} but {canonical!r} "
                f"is not registered"
            )

    def test_registry_unknown_id_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nope-unknown")


# ─── create_llm raises LLMNotConfiguredError ───────────────────────────


class TestCreateLLM:
    def test_disabled_raises_lal_error(self, monkeypatch):
        with pytest.raises(LLMNotConfiguredError):
            create_llm({"enabled": False, "provider": "minimax"})

    def test_no_provider_raises_lal_error(self, monkeypatch):
        with pytest.raises(LLMNotConfiguredError):
            create_llm({"enabled": True, "provider": None})

    def test_legacy_id_works(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        client = create_llm({"enabled": True, "provider": "minimax"})
        assert client.provider == "minimax"  # aliased
        assert client.api_key == "k"


# ─── Source-of-truth grep: no silent gpt-4o in business code ──────────


class TestNoSilentGPT4OInBusinessCode:
    """Scan key business files for any remaining silent gpt-4o
    fallback in the ``__init__`` default-args path.

    PR 4 contract:
      - ``LLMClient.__init__()`` and
        ``StreamableLLMClient.__init__()`` MUST NOT default to
        gpt-4o / openai. LLMNotConfiguredError is the new behaviour.
      - The legacy ``from_config`` paths are preserved behind the
        ``LLM_LEGACY_FALLBACK`` gradient switch (default off) so
        the test focuses on the no-arg constructor path.

    The token-estimator / token-budget / context-windows files are
    intentionally EXEMPT — they keep their defaults because token
    estimation must always return *something*."""

    EXEMPT_PATHS = (
        "src/llmwikify/foundation/llm/token_estimator.py",
        "src/llmwikify/foundation/llm/token_budget.py",
        "src/llmwikify/foundation/llm/context_windows.py",
    )

    INIT_SCAN_PATHS = (
        "src/llmwikify/foundation/llm_client.py",
        "src/llmwikify/foundation/llm/streamable.py",
    )

    def test_no_gpt4o_default_in_llm_client_init(self):
        repo = Path(__file__).resolve().parent.parent
        full = repo / "src/llmwikify/foundation/llm_client.py"
        content = full.read_text(encoding="utf-8")
        # The __init__ default-arg list must not include "gpt-4o".
        # We isolate the signature between ( and ) using DOTALL to
        # handle multi-line signatures.
        import re
        sig_match = re.search(
            r"def __init__\s*\((.*?)\)\s*:",
            content, re.DOTALL,
        )
        assert sig_match, "could not locate LLMClient.__init__ signature"
        sig = sig_match.group(1)
        assert '"gpt-4o"' not in sig, (
            "LLMClient.__init__ signature still defaults to 'gpt-4o'"
        )
        assert "'gpt-4o'" not in sig

    def test_no_gpt4o_default_in_streamable_init(self):
        repo = Path(__file__).resolve().parent.parent
        full = repo / "src/llmwikify/foundation/llm/streamable.py"
        content = full.read_text(encoding="utf-8")
        import re
        sig_match = re.search(
            r"def __init__\s*\((.*?)\)\s*:",
            content, re.DOTALL,
        )
        assert sig_match, "could not locate StreamableLLMClient.__init__ signature"
        sig = sig_match.group(1)
        assert '"gpt-4o"' not in sig, (
            "StreamableLLMClient.__init__ signature still defaults to 'gpt-4o'"
        )
        assert "'gpt-4o'" not in sig

    def test_no_getattr_gpt4o_fallback_in_business_code(self):
        # The pre-PR-4 silent fallback pattern was:
        #   getattr(model, "model", "gpt-4o")
        # PR 4 removes this from the listed files.
        repo = Path(__file__).resolve().parent.parent
        files_to_check = (
            "src/llmwikify/apps/chat/agent/service.py",
            "src/llmwikify/apps/chat/agent/orchestrator.py",
            "src/llmwikify/apps/chat/agent/context_manager.py",
        )
        for rel in files_to_check:
            full = repo / rel
            if not full.exists():
                continue
            content = full.read_text(encoding="utf-8")
            assert 'getattr(' not in content or '"gpt-4o"' not in content, (
                f"{rel} still has getattr(..., 'gpt-4o') fallback"
            )

    def test_token_estimation_files_untouched(self):
        # Sanity: ensure the exempt files are still there.
        repo = Path(__file__).resolve().parent.parent
        for rel in self.EXEMPT_PATHS:
            full = repo / rel
            assert full.exists(), f"expected exempt file {rel} missing"
