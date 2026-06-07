"""Unit tests for autoresearch._json_utils.safe_json_loads."""

from __future__ import annotations

import json

import pytest

from llmwikify.apps.chat.engine_helpers import safe_json_loads


class TestSafeJsonLoadsHappyPath:
    def test_plain_dict(self):
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_plain_list(self):
        assert safe_json_loads("[1, 2, 3]") == [1, 2, 3]

    def test_whitespace_stripped(self):
        assert safe_json_loads('   \n  {"a": 1}  \n  ') == {"a": 1}

    def test_nested_object(self):
        payload = {"a": {"b": [1, 2, {"c": "x"}]}}
        assert safe_json_loads(json.dumps(payload)) == payload

    def test_unicode_strings(self):
        assert safe_json_loads('{"name": "中文 / 🎉"}') == {"name": "中文 / 🎉"}


class TestSafeJsonLoadsMarkdownFence:
    def test_json_fence(self):
        assert safe_json_loads('```json\n{"a": 1}\n```') == {"a": 1}

    def test_plain_fence(self):
        assert safe_json_loads('```\n{"a": 1}\n```') == {"a": 1}

    def test_fence_no_closing(self):
        # No closing fence — should still parse the inner JSON
        assert safe_json_loads('```json\n{"a": 1}') == {"a": 1}

    def test_fence_with_surrounding_prose(self):
        text = 'Sure! Here you go:\n```json\n{"a": 1}\n```\nHope that helps.'
        # Fence strip leaves '{"a": 1}\n```\nHope that helps.'
        # Direct parse fails at '\n```'. raw_decode finds the first
        # valid JSON value ({"a": 1}) and ignores the rest.
        assert safe_json_loads(text) == {"a": 1}


class TestSafeJsonLoadsTrailingProse:
    def test_trailing_note(self):
        # First 13 lines parse OK, but text continues after final '}'
        text = '{"a": 1}\n\nNote: I also recommend checking the docs.'
        assert safe_json_loads(text) == {"a": 1}

    def test_two_adjacent_objects(self):
        # LLM sometimes outputs JSON + extra object
        # raw_decode returns the FIRST valid JSON value, so we get {"a": 1}
        text = '{"a": 1}\n{"b": 2}'
        assert safe_json_loads(text) == {"a": 1}

    def test_long_preamble(self):
        text = 'Here is the JSON you requested:\n\n{"a": 1}'
        # Fence strip is no-op, full parse fails at "Here"
        # raw_decode finds the first valid JSON value ({...}) and
        # ignores the leading prose
        assert safe_json_loads(text) == {"a": 1}


class TestSafeJsonLoadsEmpty:
    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError) as excinfo:
            safe_json_loads("")
        assert "empty" in str(excinfo.value).lower()

    def test_whitespace_only_raises(self):
        with pytest.raises(json.JSONDecodeError) as excinfo:
            safe_json_loads("   \n\t  ")
        assert "empty" in str(excinfo.value).lower()

    def test_fence_only_raises(self):
        with pytest.raises(json.JSONDecodeError) as excinfo:
            safe_json_loads("```json\n```")
        assert "empty" in str(excinfo.value).lower()

    def test_none_raises(self):
        with pytest.raises(json.JSONDecodeError) as excinfo:
            safe_json_loads(None)  # type: ignore[arg-type]
        assert "empty" in str(excinfo.value).lower()


class TestSafeJsonLoadsStrictMode:
    def test_strict_disables_truncation(self):
        text = 'Here is the JSON you requested:\n\n{"a": 1}'
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads(text, allow_truncate=False)

    def test_strict_does_not_affect_fence(self):
        # Fence strip is always applied (not part of truncation rescue)
        assert safe_json_loads(
            '```json\n{"a": 1}\n```', allow_truncate=False
        ) == {"a": 1}

    def test_strict_empty_still_raises(self):
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads("", allow_truncate=False)


class TestSafeJsonLoadsGenuinelyBroken:
    def test_no_brace_raises(self):
        # Even with truncation, no balanced brace exists
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads("totally not json")

    def test_open_brace_only_raises(self):
        # No complete JSON value in the string. raw_decode cannot rescue.
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads('{"a":')

    def test_nested_truncated_raises(self):
        # Truly broken JSON — inner dict is missing closing brace
        # AND the outer is too. raw_decode starting at first '{'
        # cannot recover a complete value.
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads('{"outer": {"inner": 1')
