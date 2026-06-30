"""Unit tests for llmwikify.autoresearch.engine_helpers.resolve_llm_params.

The helper must be a single source of truth for LLM call params with
a 3-layer priority chain: caller config > prompt registry > safety
net (DEFAULT_LLM_PARAMS).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.engine_helpers import (
    DEFAULT_LLM_PARAMS,
    resolve_llm_params,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


def _make_registry(params: dict) -> MagicMock:
    """Build a MagicMock PromptRegistry returning the given api params."""
    registry = MagicMock()
    registry.get_api_params = MagicMock(return_value=params)
    return registry


# -----------------------------------------------------------------------------
# Layer 3 (safety net) — registry=None, config=None
# -----------------------------------------------------------------------------


def test_safety_net_only_when_registry_and_config_missing():
    """No registry + no config → all 3 params come from DEFAULT_LLM_PARAMS."""
    result = resolve_llm_params(registry=None, config=None, prompt_name="research_plan")
    assert result == {
        "max_tokens": DEFAULT_LLM_PARAMS["max_tokens"],
        "temperature": DEFAULT_LLM_PARAMS["temperature"],
        "json_mode": DEFAULT_LLM_PARAMS["json_mode"],
    }


def test_safety_net_used_when_registry_returns_empty():
    """Registry returns empty dict → falls through to safety net."""
    registry = _make_registry({})
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name="research_plan"
    )
    assert result["max_tokens"] == DEFAULT_LLM_PARAMS["max_tokens"]
    assert result["temperature"] == DEFAULT_LLM_PARAMS["temperature"]
    assert result["json_mode"] == DEFAULT_LLM_PARAMS["json_mode"]


def test_safety_net_used_when_config_section_missing():
    """config_section not in config dict → falls through to registry / safety net."""
    registry = _make_registry({})
    result = resolve_llm_params(
        registry=registry,
        config={"unrelated_key": 1},
        prompt_name="research_plan",
        config_section="llm_params.plan",
    )
    assert result["max_tokens"] == DEFAULT_LLM_PARAMS["max_tokens"]


# -----------------------------------------------------------------------------
# Layer 2 (registry) — registry present, config missing
# -----------------------------------------------------------------------------


def test_registry_provides_max_tokens():
    """Registry's max_tokens is used when config is absent."""
    registry = _make_registry({"max_tokens": 8192, "temperature": 0.1, "json_mode": False})
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name="research_report"
    )
    assert result["max_tokens"] == 8192
    assert result["temperature"] == 0.1
    assert result["json_mode"] is False


def test_registry_consulted_with_correct_prompt_name():
    """Registry is queried with the exact prompt_name argument."""
    registry = _make_registry({"max_tokens": 4096})
    resolve_llm_params(registry=registry, config=None, prompt_name="research_review")
    registry.get_api_params.assert_called_once_with("research_review")


def test_registry_only_returns_recognized_params():
    """Unknown keys in registry output are ignored; safety net fills in."""
    registry = _make_registry({"max_tokens": 4096, "bogus_key": "ignored"})
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name="research_plan"
    )
    assert result["max_tokens"] == 4096
    assert "bogus_key" not in result
    assert result["temperature"] == DEFAULT_LLM_PARAMS["temperature"]


# -----------------------------------------------------------------------------
# Layer 1 (config) — highest priority
# -----------------------------------------------------------------------------


def test_config_overrides_registry():
    """Caller config wins over registry."""
    registry = _make_registry({"max_tokens": 1024, "temperature": 0.1, "json_mode": False})
    config = {
        "llm_params": {
            "research_plan": {"max_tokens": 7777, "temperature": 0.9, "json_mode": True},
        }
    }
    result = resolve_llm_params(
        registry=registry,
        config=config,
        prompt_name="research_plan",
        config_section="llm_params",
    )
    assert result["max_tokens"] == 7777
    assert result["temperature"] == 0.9
    assert result["json_mode"] is True


def test_config_partial_override_falls_back_to_registry():
    """Config sets only some params → others come from registry."""
    registry = _make_registry({"max_tokens": 1024, "temperature": 0.1, "json_mode": True})
    config = {"llm_params": {"research_plan": {"max_tokens": 999}}}
    result = resolve_llm_params(
        registry=registry,
        config=config,
        prompt_name="research_plan",
        config_section="llm_params",
    )
    assert result["max_tokens"] == 999  # from config
    assert result["temperature"] == 0.1  # from registry
    assert result["json_mode"] is True  # from registry


def test_config_per_prompt_independence():
    """Per-prompt config: only the targeted prompt is overridden."""
    registry = _make_registry({"max_tokens": 1024})
    config = {
        "llm_params": {
            "research_plan": {"max_tokens": 7777},
            "research_report": {"max_tokens": 9999},
        }
    }
    plan = resolve_llm_params(
        registry=registry, config=config, prompt_name="research_plan",
        config_section="llm_params",
    )
    report = resolve_llm_params(
        registry=registry, config=config, prompt_name="research_report",
        config_section="llm_params",
    )
    assert plan["max_tokens"] == 7777
    assert report["max_tokens"] == 9999


def test_config_section_is_dict_with_unrelated_prompts_ignored():
    """Other prompt entries in the section don't affect our resolution."""
    registry = _make_registry({"max_tokens": 1024})
    config = {
        "llm_params": {
            "research_plan": {"max_tokens": 7777},
            "research_report": {"max_tokens": 9999},
        }
    }
    result = resolve_llm_params(
        registry=registry, config=config, prompt_name="research_review",
        config_section="llm_params",
    )
    assert result["max_tokens"] == 1024  # falls through to registry


def test_config_empty_section_falls_back_to_registry():
    """config[config_section] exists but is empty → registry wins."""
    registry = _make_registry({"max_tokens": 2048, "temperature": 0.2, "json_mode": True})
    config = {"llm_params": {}}
    result = resolve_llm_params(
        registry=registry,
        config=config,
        prompt_name="research_plan",
        config_section="llm_params",
    )
    assert result["max_tokens"] == 2048


# -----------------------------------------------------------------------------
# Error tolerance
# -----------------------------------------------------------------------------


def test_registry_raises_filenotfound_falls_back_gracefully(caplog):
    """If prompt not found, log debug and use safety net."""
    registry = MagicMock()
    registry.get_api_params = MagicMock(side_effect=FileNotFoundError("missing"))
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name="nonexistent_prompt"
    )
    assert result["max_tokens"] == DEFAULT_LLM_PARAMS["max_tokens"]


def test_registry_raises_keyerror_falls_back_gracefully():
    """KeyError from registry → use safety net."""
    registry = MagicMock()
    registry.get_api_params = MagicMock(side_effect=KeyError("k"))
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name="x"
    )
    assert result["temperature"] == DEFAULT_LLM_PARAMS["temperature"]


def test_config_section_none_skips_config_layer():
    """config_section=None → config is ignored entirely."""
    registry = _make_registry({"max_tokens": 1024})
    config = {"llm_params": {"plan": {"max_tokens": 99999}}}
    result = resolve_llm_params(
        registry=registry, config=config, prompt_name="research_plan", config_section=None
    )
    assert result["max_tokens"] == 1024  # registry, not config


def test_prompt_name_empty_string_skips_registry():
    """prompt_name="" → registry not consulted."""
    registry = MagicMock()
    registry.get_api_params = MagicMock(return_value={"max_tokens": 1024})
    result = resolve_llm_params(
        registry=registry, config=None, prompt_name=""
    )
    registry.get_api_params.assert_not_called()
    assert result["max_tokens"] == DEFAULT_LLM_PARAMS["max_tokens"]


# -----------------------------------------------------------------------------
# Return shape
# -----------------------------------------------------------------------------


def test_return_shape_always_three_keys():
    """Result always has exactly 3 keys, in stable order."""
    result = resolve_llm_params(registry=None, config=None, prompt_name="x")
    assert set(result.keys()) == {"max_tokens", "temperature", "json_mode"}


def test_types_are_stable():
    """Return types are int / float / bool (not str or None)."""
    result = resolve_llm_params(registry=None, config=None, prompt_name="x")
    assert isinstance(result["max_tokens"], int)
    assert isinstance(result["temperature"], float)
    assert isinstance(result["json_mode"], bool)


# -----------------------------------------------------------------------------
# Integration with chat_json signature
# -----------------------------------------------------------------------------


def test_output_unpacks_into_chat_json_kwargs():
    """resolve_llm_params output can be **-unpacked into chat_json."""
    import inspect

    from llmwikify.apps.chat.engine_helpers import chat_json

    result = resolve_llm_params(
        registry=_make_registry({}), config=None, prompt_name="research_plan"
    )
    sig = inspect.signature(chat_json)
    for key in ("max_tokens", "temperature", "json_mode"):
        assert key in sig.parameters, f"chat_json must accept {key}"
    # The dict should have no extra keys that chat_json would reject
    assert set(result.keys()).issubset({"max_tokens", "temperature", "json_mode"})


# -----------------------------------------------------------------------------
# Real PromptRegistry integration smoke test
# -----------------------------------------------------------------------------


def test_with_real_prompt_registry_research_plan(tmp_path, monkeypatch):
    """Smoke test: real PromptRegistry loading a built-in prompt."""
    from llmwikify.kernel.wiki.prompt_registry import PromptRegistry

    # Use the default prompts directory (no custom dir)
    registry = PromptRegistry(provider="openai")
    result = resolve_llm_params(
        registry=registry,
        config=None,
        prompt_name="research_plan",
    )
    # The built-in research_plan.yaml should declare max_tokens / temperature.
    # At minimum, all 3 keys must be present and typed correctly.
    assert isinstance(result["max_tokens"], int)
    assert isinstance(result["temperature"], float)
    assert isinstance(result["json_mode"], bool)
