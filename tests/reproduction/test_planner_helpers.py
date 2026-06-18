"""Tests for planner helper functions: _clamp_token_budget, _extract_json, PlanResult."""
from __future__ import annotations

import json

import pytest

from llmwikify.reproduction.llm_extraction.planner import (
    TOKEN_BUDGET_FLOOR,
    PlanResult,
    _clamp_token_budget,
    _extract_json,
    _parse_validation_fallback,
)


class TestExtractJson:
    def test_valid_json(self):
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_markdown(self):
        result = _extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        result = _extract_json('Here is the result: {"key": "value"} done.')
        assert result == {"key": "value"}

    def test_no_json(self):
        result = _extract_json("no json here")
        assert result is None

    def test_truncated_json_returns_none(self):
        # Planner's _extract_json doesn't repair truncated JSON
        result = _extract_json('{"key": "value", "list": [1, 2, 3')
        assert result is None

    def test_nested_json(self):
        result = _extract_json('{"outer": {"inner": 42}}')
        assert result == {"outer": {"inner": 42}}

    def test_empty_object(self):
        result = _extract_json("{}")
        assert result == {}

    def test_unicode(self):
        result = _extract_json('{"name": "量化因子"}')
        assert result["name"] == "量化因子"


class TestClampTokenBudget:
    def test_enforces_floor(self):
        budget = {"track_a_tier1": 1000, "track_b_pass1": 100}
        result = _clamp_token_budget(budget)
        assert result["track_a_tier1"] == TOKEN_BUDGET_FLOOR["track_a_tier1"]
        assert result["track_b_pass1"] == TOKEN_BUDGET_FLOOR["track_b_pass1"]

    def test_keeps_higher_values(self):
        budget = {"track_a_tier1": 10000, "track_b_pass1": 50000}
        result = _clamp_token_budget(budget)
        assert result["track_a_tier1"] == 10000
        assert result["track_b_pass1"] == 50000

    def test_unknown_key_passthrough(self):
        budget = {"unknown_key": 42}
        result = _clamp_token_budget(budget)
        assert result["unknown_key"] == 42

    def test_non_numeric_skipped(self):
        budget = {"track_a_tier1": "invalid", "track_b_pass2_per_factor": 5000}
        result = _clamp_token_budget(budget)
        assert "track_a_tier1" not in result
        assert result["track_b_pass2_per_factor"] == 5000

    def test_empty_budget(self):
        result = _clamp_token_budget({})
        assert result == {}

    def test_float_converted_to_int(self):
        budget = {"track_a_tier1": 3500.7}
        result = _clamp_token_budget(budget)
        assert isinstance(result["track_a_tier1"], int)
        assert result["track_a_tier1"] == 3500

    def test_all_floor_keys_present(self):
        budget = dict.fromkeys(TOKEN_BUDGET_FLOOR, 0)
        result = _clamp_token_budget(budget)
        for key, floor in TOKEN_BUDGET_FLOOR.items():
            assert key in result
            assert result[key] >= floor


class TestPlanResult:
    def test_defaults(self):
        r = PlanResult(paper_id="test")
        assert r.schema_choice == "summary"
        assert r.success is False
        assert r.confidence == 0.0

    def test_to_dict(self):
        r = PlanResult(
            paper_id="test",
            schema_choice="factor",
            n_signals_estimate=50,
            confidence=0.9,
        )
        d = r.to_dict()
        assert d["paper_id"] == "test"
        assert d["schema_choice"] == "factor"
        assert d["n_signals_estimate"] == 50
        assert isinstance(d, dict)

    def test_to_dict_with_error(self):
        r = PlanResult(paper_id="test", success=False, error="llm_timeout")
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "llm_timeout"


class TestParseValidationFallback:
    """Test fallback parser for LLM natural language responses."""

    def test_markdown_bold_issues(self):
        """Issues under **Potential Issues:** markdown bold header."""
        response = """**Potential Issues:**
1. The extraction strategy focuses heavily on event library
2. The n_signals_estimate of 95 seems reasonable
3. The plan appears well-structured but could benefit from more emphasis on outputs.

The extraction targets are specific."""
        is_valid, issues, suggestions, _ = _parse_validation_fallback(response)
        assert is_valid is True
        assert len(issues) == 3
        assert "event library" in issues[0]

    def test_plain_issues_header(self):
        """Issues under plain 'Issues:' header."""
        response = """Issues:
1. Wrong schema
2. Missing tables

Plan needs adjustment."""
        is_valid, issues, _, _ = _parse_validation_fallback(response)
        assert is_valid is True  # No explicit "is_valid: false"
        assert len(issues) == 2

    def test_explicit_rejection(self):
        """Explicit 'is_valid: false' or 'rejected' → invalid."""
        response = """**Issues:**
1. Schema is completely wrong

is_valid: false

This plan must be rejected."""
        is_valid, issues, _, _ = _parse_validation_fallback(response)
        assert is_valid is False
        assert len(issues) == 1

    def test_suggestions_markdown(self):
        """Suggestions under **Suggestions:** header."""
        response = """**Suggestions:**
- Add more detail about allocation outputs
- Consider breaking down 28 industries

End of analysis."""
        is_valid, _, suggestions, _ = _parse_validation_fallback(response)
        assert is_valid is True
        assert len(suggestions) == 2
        assert "allocation" in suggestions[0]

    def test_blank_line_separator(self):
        """Blank lines between bullets should not break extraction."""
        response = """**Issues:**
1. First issue


2. Second issue after blank lines

End."""
        is_valid, issues, _, _ = _parse_validation_fallback(response)
        assert is_valid is True
        assert len(issues) == 2

    def test_no_issues_returns_valid(self):
        """No 'Issues:' section and positive markers → valid."""
        response = """This plan is appropriate. is_valid: true."""
        is_valid, issues, _, _ = _parse_validation_fallback(response)
        assert is_valid is True
        assert len(issues) == 0

    def test_revised_strategy_extraction(self):
        """Extract revised_strategy when explicitly mentioned."""
        response = """Revised strategy: Extract only representative industries and skip duplicates.

**Issues:**
1. Old strategy was too broad."""
        is_valid, _, _, revised = _parse_validation_fallback(response)
        assert "representative industries" in revised.lower()

    def test_prose_termination(self):
        """Prose after bullets should not pollute last bullet."""
        response = """**Suggestions:**
- First suggestion
- Second suggestion

This is just summary prose, not a bullet."""
        is_valid, _, suggestions, _ = _parse_validation_fallback(response)
        assert len(suggestions) == 2
        assert "summary prose" not in suggestions[1]

    def test_chinese_text(self):
        """Chinese paper text handling."""
        response = """**Issues:**
1. 提取策略应该更详细
2. 信号数量估计过高

结论：建议重新规划。"""
        is_valid, issues, _, _ = _parse_validation_fallback(response)
        assert is_valid is True
        assert len(issues) == 2
        assert "提取策略" in issues[0]
