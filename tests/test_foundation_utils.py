"""Tests for foundation.utils — shared utility functions."""
from __future__ import annotations

from typing import Any

import pytest

from llmwikify.foundation.utils import deep_merge, mask_api_key


class TestDeepMerge:
    """Tests for deep_merge() function."""

    def test_empty_dicts(self) -> None:
        """Merging empty dicts returns empty dict."""
        assert deep_merge({}, {}) == {}

    def test_no_overlap(self) -> None:
        """Non-overlapping keys are merged."""
        result = deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_override_takes_precedence(self) -> None:
        """Override values take precedence."""
        result = deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_nested_dict_merge(self) -> None:
        """Nested dicts are merged recursively."""
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 3, "z": 4}}

    def test_deep_nested_merge(self) -> None:
        """Deeply nested dicts are merged."""
        base = {"a": {"b": {"c": 1}}}
        override = {"a": {"b": {"d": 2}}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 2}}}

    def test_override_replaces_non_dict(self) -> None:
        """Override replaces non-dict values with dict."""
        base = {"a": 1}
        override = {"a": {"x": 2}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 2}}

    def test_override_replaces_dict_with_non_dict(self) -> None:
        """Override replaces dict with non-dict."""
        base = {"a": {"x": 1}}
        override = {"a": 2}
        result = deep_merge(base, override)
        assert result == {"a": 2}

    def test_originals_not_modified(self) -> None:
        """Original dicts are not modified."""
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge(base, override)
        assert base == {"a": {"x": 1}}
        assert override == {"a": {"y": 2}}
        assert result == {"a": {"x": 1, "y": 2}}


class TestMaskApiKey:
    """Tests for mask_api_key() function."""

    def test_no_api_key(self) -> None:
        """Config without api_key returns unchanged."""
        config = {"provider": "openai"}
        result = mask_api_key(config)
        assert result == {"provider": "openai"}

    def test_empty_api_key(self) -> None:
        """Empty api_key returns unchanged."""
        config = {"api_key": ""}
        result = mask_api_key(config)
        assert result == {"api_key": ""}

    def test_env_prefix(self) -> None:
        """env: prefix is masked to env:***."""
        config = {"api_key": "env:MY_API_KEY"}
        result = mask_api_key(config)
        assert result == {"api_key": "env:***"}

    def test_long_key(self) -> None:
        """Long keys show first 4 and last 4 chars."""
        config = {"api_key": "sk-1234567890abcdef"}
        result = mask_api_key(config)
        assert result == {"api_key": "sk-1***cdef"}

    def test_short_key(self) -> None:
        """Short keys are fully masked."""
        config = {"api_key": "short"}
        result = mask_api_key(config)
        assert result == {"api_key": "***"}

    def test_exact_8_chars(self) -> None:
        """8-char keys are fully masked."""
        config = {"api_key": "12345678"}
        result = mask_api_key(config)
        assert result == {"api_key": "***"}

    def test_9_chars(self) -> None:
        """9-char keys show first 4 and last 4."""
        config = {"api_key": "123456789"}
        result = mask_api_key(config)
        assert result == {"api_key": "1234***6789"}

    def test_original_not_modified(self) -> None:
        """Original config is not modified."""
        config = {"api_key": "sk-1234567890abcdef"}
        result = mask_api_key(config)
        assert config["api_key"] == "sk-1234567890abcdef"
        assert result["api_key"] == "sk-1***cdef"

    def test_preserves_other_fields(self) -> None:
        """Other fields are preserved."""
        config = {"api_key": "sk-1234567890abcdef", "provider": "openai", "model": "gpt-4"}
        result = mask_api_key(config)
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4"
