"""Phase 16 — LLMProvider ABC + ProviderConfig + RetryMode + ThinkingStyle tests.

Borrowed from nanobot v0.2.1 ``providers/base.py`` design (see
``docs/poc/apply-plan.md`` \u00a716 for context).

Covers:
  - RetryMode enum values + str comparison
  - ThinkingStyle: 10+ values + extra_body() mapping + default()
  - ProviderConfig: from_dict (wrapped + flat + bad enums) + to_dict round-trip + is_configured()
  - LLMProviderABC: abstract enforcement + apply_snapshot noop default +
    supported_retry_modes / supported_thinking_styles defaults + thinking_style_prompt default
  - Backward compat: existing Protocol + BaseLLMProvider + XiaomiProvider + MiniMaxProvider still work
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from llmwikify.apps.chat.providers.abc import (
    LLMProviderABC,
    ProviderConfig,
    RetryMode,
    ThinkingStyle,
)
from llmwikify.apps.chat.providers.base import BaseLLMProvider, LLMProvider
from llmwikify.apps.chat.providers.minimax import MiniMaxProvider
from llmwikify.apps.chat.providers.registry import (
    PROVIDERS,
    create_llm,
    get_provider,
    list_providers,
)
from llmwikify.apps.chat.providers.xiaomi import XiaomiProvider

# ── RetryMode ───────────────────────────────────────────────────


class TestRetryMode:
    def test_values(self) -> None:
        assert RetryMode.TRANSIENT.value == "transient"
        assert RetryMode.PERSISTENT.value == "persistent"
        assert RetryMode.OFF.value == "off"
        assert RetryMode.AGGRESSIVE.value == "aggressive"

    def test_count(self) -> None:
        # Borrowed 4 modes from nanobot v0.2.1
        assert len(list(RetryMode)) == 4

    def test_str_serialization(self) -> None:
        """str enum value is JSON-serializable."""
        for mode in RetryMode:
            assert json.loads(json.dumps(mode.value)) == mode.value

    def test_construction_from_string(self) -> None:
        """``RetryMode("persistent")`` works (str enum semantics)."""
        assert RetryMode("persistent") is RetryMode.PERSISTENT


# ── ThinkingStyle ───────────────────────────────────────────────


class TestThinkingStyle:
    def test_count_is_10_plus(self) -> None:
        """Borrowed 10+ styles from nanobot v0.2.1."""
        assert len(list(ThinkingStyle)) >= 10

    def test_default(self) -> None:
        assert ThinkingStyle.default() is ThinkingStyle.MINIMAL

    def test_values(self) -> None:
        """All enum values are lowercase (snake or kebab case)."""
        for style in ThinkingStyle:
            assert style.value == style.value.lower()
            # No spaces / punctuation that would break config parsing
            assert " " not in style.value
            # Only ASCII letters, digits, underscore, hyphen allowed
            assert all(
                ch.isalnum() or ch in ("_", "-") for ch in style.value
            )

    @pytest.mark.parametrize(
        "style,expected_keys",
        [
            (ThinkingStyle.MINIMAL, set()),
            (ThinkingStyle.DETAILED, {"reasoning_effort"}),
            (ThinkingStyle.EXHAUSTIVE, {"reasoning_effort", "temperature"}),
            (ThinkingStyle.BUDGET_AWARE, {"reasoning_effort"}),
            (ThinkingStyle.COMPACT, {"reasoning_effort"}),
            # Styles that depend on prompt injection return empty body
            (ThinkingStyle.STEP_BY_STEP, set()),
            (ThinkingStyle.CODE_FIRST, set()),
            (ThinkingStyle.SAFE_FIRST, set()),
            (ThinkingStyle.SUMMARY_FIRST, set()),
            (ThinkingStyle.TOOL_FIRST, set()),
            (ThinkingStyle.ANALYTICAL, set()),
        ],
    )
    def test_extra_body_keys(self, style: ThinkingStyle, expected_keys: set) -> None:
        body = style.extra_body()
        assert set(body.keys()) == expected_keys

    def test_extra_body_does_not_mutate_class(self) -> None:
        """Calling extra_body() multiple times returns fresh dicts."""
        d1 = ThinkingStyle.EXHAUSTIVE.extra_body()
        d2 = ThinkingStyle.EXHAUSTIVE.extra_body()
        assert d1 == d2
        assert d1 is not d2  # Fresh dict each time

    def test_detailed_extra_body_values(self) -> None:
        assert ThinkingStyle.DETAILED.extra_body() == {"reasoning_effort": "high"}

    def test_compact_extra_body_values(self) -> None:
        assert ThinkingStyle.COMPACT.extra_body() == {"reasoning_effort": "low"}


# ── ProviderConfig ──────────────────────────────────────────────


class TestProviderConfig:
    def test_defaults(self) -> None:
        cfg = ProviderConfig()
        assert cfg.provider == ""
        assert cfg.model == ""
        assert cfg.enabled is False
        assert cfg.retry_mode is RetryMode.TRANSIENT
        assert cfg.thinking_style is ThinkingStyle.MINIMAL
        assert cfg.max_tokens is None
        assert cfg.temperature is None
        assert cfg.extra == {}

    def test_from_dict_flat_shape(self) -> None:
        cfg = ProviderConfig.from_dict({
            "provider": "minimax",
            "model": "minimax-M3",
            "api_key": "sk-x",
            "base_url": "https://api.minimaxi.com/v1",
            "enabled": True,
        })
        assert cfg.provider == "minimax"
        assert cfg.model == "minimax-M3"
        assert cfg.api_key == "sk-x"
        assert cfg.base_url == "https://api.minimaxi.com/v1"
        assert cfg.enabled is True

    def test_from_dict_wrapped_llm_shape(self) -> None:
        """``{"llm": {...}}`` shape (mirrors ``create_llm()``)."""
        cfg = ProviderConfig.from_dict({
            "llm": {"provider": "minimax", "model": "M3", "api_key": "sk-x"},
        })
        assert cfg.provider == "minimax"
        assert cfg.model == "M3"

    def test_from_dict_enum_coercion(self) -> None:
        cfg = ProviderConfig.from_dict({
            "retry_mode": "persistent",
            "thinking_style": "exhaustive",
        })
        assert cfg.retry_mode is RetryMode.PERSISTENT
        assert cfg.thinking_style is ThinkingStyle.EXHAUSTIVE

    def test_from_dict_bad_enum_falls_back_to_default(self) -> None:
        cfg = ProviderConfig.from_dict({
            "retry_mode": "BOGUS_VALUE",
            "thinking_style": "also_bogus",
        })
        assert cfg.retry_mode is RetryMode.TRANSIENT  # default
        assert cfg.thinking_style is ThinkingStyle.MINIMAL  # default

    def test_from_dict_numeric_coercion(self) -> None:
        cfg = ProviderConfig.from_dict({
            "max_tokens": 4096,
            "temperature": 0.7,
        })
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.7

    def test_from_dict_numeric_coercion_failure_drops(self) -> None:
        """Bad numeric values silently dropped (don't crash config load)."""
        cfg = ProviderConfig.from_dict({
            "max_tokens": "not_a_number",
            "temperature": [1, 2, 3],
        })
        assert cfg.max_tokens is None
        assert cfg.temperature is None

    def test_from_dict_extra_fields_go_to_extra(self) -> None:
        """Unknown keys survive round-trip via ``extra`` dict."""
        cfg = ProviderConfig.from_dict({
            "provider": "minimax",
            "top_p": 0.9,
            "frequency_penalty": 0.5,
        })
        assert cfg.extra == {"top_p": 0.9, "frequency_penalty": 0.5}

    def test_from_dict_empty_inputs(self) -> None:
        """Empty dict / None / non-dict all return a default config."""
        for empty in ({}, None, "not a dict", 42, []):
            cfg = ProviderConfig.from_dict(empty)  # type: ignore[arg-type]
            assert cfg.provider == ""
            assert cfg.enabled is False

    def test_to_dict_round_trip(self) -> None:
        original = ProviderConfig(
            provider="minimax",
            model="M3",
            api_key="sk-x",
            base_url="https://api.minimaxi.com/v1",
            enabled=True,
            retry_mode=RetryMode.PERSISTENT,
            thinking_style=ThinkingStyle.DETAILED,
            max_tokens=2048,
            temperature=0.5,
            extra={"top_p": 0.9},
        )
        d = original.to_dict()
        assert d["provider"] == "minimax"
        assert d["model"] == "M3"
        assert d["api_key"] == "sk-x"
        assert d["base_url"] == "https://api.minimaxi.com/v1"
        assert d["enabled"] is True
        assert d["retry_mode"] == "persistent"
        assert d["thinking_style"] == "detailed"
        assert d["max_tokens"] == 2048
        assert d["temperature"] == 0.5
        assert d["top_p"] == 0.9
        # Round-trip via from_dict should yield equivalent config
        restored = ProviderConfig.from_dict(d)
        assert restored.provider == original.provider
        assert restored.model == original.model
        assert restored.retry_mode == original.retry_mode
        assert restored.thinking_style == original.thinking_style
        assert restored.extra == original.extra

    def test_to_dict_drops_none_and_empty(self) -> None:
        """Optional fields with default values aren't serialized."""
        d = ProviderConfig().to_dict()
        assert "api_key" not in d  # empty string
        assert "base_url" not in d
        assert "max_tokens" not in d  # None
        assert "temperature" not in d
        assert "extra" not in d  # default empty dict

    def test_is_configured(self) -> None:
        # Not enabled
        cfg = ProviderConfig(provider="minimax", api_key="sk-x")
        assert cfg.is_configured() is False

        # Enabled but no api_key
        cfg = ProviderConfig(provider="minimax", enabled=True)
        assert cfg.is_configured() is False

        # Enabled + api_key
        cfg = ProviderConfig(
            provider="minimax", enabled=True, api_key="sk-x",
        )
        assert cfg.is_configured() is True

    def test_is_configured_with_env_syntax(self) -> None:
        cfg = ProviderConfig(
            provider="minimax",
            enabled=True,
            api_key="env:NONEXISTENT_VAR_XYZ",
        )
        assert cfg.is_configured() is False

        cfg = ProviderConfig(
            provider="minimax",
            enabled=True,
            api_key="env:PATH",
        )
        assert cfg.is_configured() is True

    def test_is_json_serializable(self) -> None:
        """to_dict output round-trips through JSON."""
        cfg = ProviderConfig(
            provider="minimax",
            enabled=True,
            retry_mode=RetryMode.PERSISTENT,
            thinking_style=ThinkingStyle.EXHAUSTIVE,
            extra={"top_p": 0.9},
        )
        encoded = json.dumps(cfg.to_dict())
        decoded = json.loads(encoded)
        assert decoded["provider"] == "minimax"
        assert decoded["retry_mode"] == "persistent"
        assert decoded["thinking_style"] == "exhaustive"


# ── LLMProviderABC ──────────────────────────────────────────────


class TestLLMProviderABC:
    def test_cannot_instantiate_directly(self) -> None:
        """ABC raises TypeError if you don't implement the abstract methods."""
        with pytest.raises(TypeError) as exc:
            LLMProviderABC()  # type: ignore[abstract]
        msg = str(exc.value).lower()
        assert "abstract" in msg

    def test_subclass_missing_one_method_still_abstract(self) -> None:
        class Incomplete(LLMProviderABC):
            def provider_name(self) -> str:
                return "x"

            # missing default_model, default_base_url, supported_models, from_config

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_with_all_methods_instantiates(self) -> None:
        class Complete(LLMProviderABC):
            def provider_name(self) -> str:
                return "test"

            def default_model(self) -> str:
                return "test-model"

            def default_base_url(self) -> str:
                return "https://test.example/v1"

            def supported_models(self) -> list[str]:
                return ["test-model"]

            def from_config(self, config):
                return "fake-client"

        p = Complete()
        assert p.provider_name() == "test"

    def test_apply_snapshot_default_is_noop(self) -> None:
        """Default apply_snapshot returns None (does nothing)."""
        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                return "c"

        p = P()
        # Snapshot with ProviderConfig
        snapshot = ProviderConfig(provider="p", model="m2")
        assert p.apply_snapshot(snapshot) is None
        # Snapshot with dict (also accepted)
        assert p.apply_snapshot({"model": "m3"}) is None

    def test_supported_retry_modes_default(self) -> None:
        """Default: only TRANSIENT."""

        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                return "c"

        p = P()
        assert p.supported_retry_modes() == [RetryMode.TRANSIENT]

    def test_supported_thinking_styles_default_includes_all(self) -> None:
        """Default: every ThinkingStyle value is supported."""

        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                return "c"

        p = P()
        assert set(p.supported_thinking_styles()) == set(ThinkingStyle)

    def test_thinking_style_prompt_default_empty(self) -> None:
        """Default thinking_style_prompt returns empty string."""

        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                return "c"

        p = P()
        assert p.thinking_style_prompt(ThinkingStyle.STEP_BY_STEP) == ""

    def test_concrete_subclass_can_override_apply_snapshot(self) -> None:
        """Subclasses with mutable state can override apply_snapshot."""

        class P(LLMProviderABC):
            def __init__(self) -> None:
                self.current_model = "default"

            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return self.current_model

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return [self.current_model]

            def from_config(self, config):
                return "c"

            def apply_snapshot(self, snapshot):
                if isinstance(snapshot, dict) and "model" in snapshot:
                    self.current_model = snapshot["model"]
                elif isinstance(snapshot, ProviderConfig):
                    self.current_model = snapshot.model or self.current_model

        p = P()
        assert p.default_model() == "default"
        p.apply_snapshot({"model": "hot-model"})
        assert p.default_model() == "hot-model"
        p.apply_snapshot(ProviderConfig(model="new-model"))
        assert p.default_model() == "new-model"


# ── from_config accepts both dict and ProviderConfig ──────────


class TestABCFromConfigPolymorphism:
    """Subclasses implementing ``from_config(config)`` should accept
    either a dict or a ProviderConfig; the base class signature is
    ``dict | ProviderConfig``."""

    def test_subclass_accepts_dict(self) -> None:
        captured: list[Any] = []

        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                captured.append(config)
                return "client"

        p = P()
        p.from_config({"provider": "x"})
        assert isinstance(captured[0], dict)

    def test_subclass_accepts_provider_config(self) -> None:
        captured: list[Any] = []

        class P(LLMProviderABC):
            def provider_name(self) -> str:
                return "p"

            def default_model(self) -> str:
                return "m"

            def default_base_url(self) -> str:
                return "u"

            def supported_models(self) -> list[str]:
                return ["m"]

            def from_config(self, config):
                captured.append(config)
                return "client"

        p = P()
        cfg = ProviderConfig(provider="x")
        p.from_config(cfg)
        assert captured[0] is cfg


# ── Backward compat: existing providers still work ─────────────


class TestBackwardCompat:
    def test_minimax_still_registers(self) -> None:
        """The existing MiniMaxProvider still works (Protocol-based)."""
        p = get_provider("minimax")
        assert isinstance(p, MiniMaxProvider)

    def test_xiaomi_still_registers(self) -> None:
        p = get_provider("xiaomi")
        assert isinstance(p, XiaomiProvider)

    def test_list_providers_includes_builtins(self) -> None:
        names = list_providers()
        assert "minimax" in names
        assert "xiaomi" in names

    def test_minimax_supports_legacy_from_config(self) -> None:
        """The existing MiniMaxProvider.from_config accepts a dict
        (Phase 16 adds typed ProviderConfig support as opt-in)."""
        p = get_provider("minimax")
        # Even with no api_key, the method signature is still compatible
        assert hasattr(p, "from_config")
        assert callable(p.from_config)

    def test_existing_protocol_still_works(self) -> None:
        """``LLMProvider`` Protocol from base.py is unchanged."""
        assert LLMProvider is not None
        # XiaomiProvider implements the Protocol
        p = XiaomiProvider()
        assert isinstance(p, LLMProvider)

    def test_base_llm_provider_still_works(self) -> None:
        """``BaseLLMProvider`` helper methods unchanged."""
        p = XiaomiProvider()
        # Helper methods still callable
        assert p._resolve_field({"x": "y"}, "x", "default") == "y"
        assert p._resolve_field({}, "missing", "default") == "default"

    def test_protocol_subclass_protocol_compat(self) -> None:
        """LLMProviderABC and LLMProvider are NOT the same class.
        Providers must opt-in to one or the other. This documents
        the dual API surface (Phase 16 keeps both)."""
        from abc import ABC as _ABC

        assert LLMProviderABC is not LLMProvider
        assert issubclass(LLMProviderABC, _ABC)


# ── End-to-end: ABC provider with all features wired ──────────


class TestEndToEndABCProvider:
    """A full ABC implementation with apply_snapshot + retry_modes +
    thinking_styles demonstrates the abstraction is usable end-to-end."""

    def test_full_abc_provider(self) -> None:
        @dataclass
        class FullProviderState:
            current_model: str = "default"
            current_retry_mode: RetryMode = RetryMode.TRANSIENT

        class FullProvider(LLMProviderABC):
            name: ClassVar[str] = "full"

            def __init__(self) -> None:
                self._state = FullProviderState()
                self.client = None

            def provider_name(self) -> str:
                return "full"

            def default_model(self) -> str:
                return self._state.current_model

            def default_base_url(self) -> str:
                return "https://full.example/v1"

            def supported_models(self) -> list[str]:
                return ["default", "smart", "fast"]

            def from_config(self, config):
                # Accept dict | ProviderConfig
                if isinstance(config, dict):
                    cfg = ProviderConfig.from_dict(config)
                else:
                    cfg = config
                self._state.current_model = cfg.model or self.default_model()
                self._state.current_retry_mode = cfg.retry_mode
                self.client = f"client(model={self._state.current_model})"
                return self.client

            def supported_retry_modes(self) -> list[RetryMode]:
                # Custom: also support PERSISTENT for dev
                return [RetryMode.TRANSIENT, RetryMode.PERSISTENT, RetryMode.OFF]

            def supported_thinking_styles(self) -> list[ThinkingStyle]:
                # Custom: only MINIMAL + DETAILED
                return [ThinkingStyle.MINIMAL, ThinkingStyle.DETAILED]

            def apply_snapshot(self, snapshot):
                if isinstance(snapshot, dict):
                    cfg = ProviderConfig.from_dict(snapshot)
                else:
                    cfg = snapshot
                self._state.current_model = cfg.model or self._state.current_model
                self._state.current_retry_mode = cfg.retry_mode

            def thinking_style_prompt(self, style):
                if style == ThinkingStyle.STEP_BY_STEP:
                    return "Think step by step."
                if style == ThinkingStyle.SAFE_FIRST:
                    return "When unsure, prefer refusal."
                return ""

        from typing import ClassVar

        p = FullProvider()

        # Initial state
        assert p.default_model() == "default"
        assert "transient" in [m.value for m in p.supported_retry_modes()]
        assert ThinkingStyle.EXHAUSTIVE not in p.supported_thinking_styles()

        # from_config with dict
        client = p.from_config({
            "model": "smart",
            "retry_mode": "persistent",
            "thinking_style": "detailed",
        })
        assert client == "client(model=smart)"
        assert p.default_model() == "smart"

        # apply_snapshot hot-swap (no rebuild)
        p.apply_snapshot({"model": "fast"})
        assert p.default_model() == "fast"
        assert p.client == "client(model=smart)"  # NOT rebuilt

        # apply_snapshot with ProviderConfig
        p.apply_snapshot(ProviderConfig(model="smart", retry_mode=RetryMode.OFF))
        assert p.default_model() == "smart"

        # thinking_style_prompt override
        assert p.thinking_style_prompt(ThinkingStyle.STEP_BY_STEP) == "Think step by step."
        assert p.thinking_style_prompt(ThinkingStyle.MINIMAL) == ""
