"""Tests for PPT rules engine — v0.6.2.patch1 two_column fallback.

Covers:
- TYPE_TO_LAYOUT mapping (resolve_layout)
- Bullets → two_column upgrade threshold (5 vs 6 items)
- v0.6.2.patch1 fallback: split flat bullets into left/right when both
  columns are empty (the rendering fix for "理论机制解析" bug)
- Defensive: existing left/right preserved, partial data not triggered,
  bullets layout not affected
"""

import pytest

from llmwikify.apps.ppt.rules import (
    TYPE_TO_LAYOUT,
    resolve_layout,
    validate_content_for_layout,
)


# ─── resolve_layout tests ──────────────────────────────────────────────


class TestResolveLayout:
    """Content_type → layout mapping."""

    def test_intro_maps_to_title(self):
        assert resolve_layout("intro", {}) == "title"

    def test_section_maps_to_section(self):
        assert resolve_layout("section", {}) == "section"

    def test_quote_maps_to_quote(self):
        assert resolve_layout("quote", {}) == "quote"

    def test_summary_maps_to_title_content(self):
        assert resolve_layout("summary", {}) == "title_content"

    def test_comparison_maps_to_two_column(self):
        """The screenshot bug: comparison must be two_column."""
        assert resolve_layout("comparison", {}) == "two_column"
        assert TYPE_TO_LAYOUT["comparison"] == "two_column"

    def test_bullets_5_items_stays_bullets(self):
        """Boundary: 5 items → bullets (not split into columns)."""
        assert resolve_layout("bullets", {"bullets": ["a"] * 5}) == "bullets"

    def test_bullets_6_items_upgrades_to_two_column(self):
        """Boundary: 6 items → two_column (auto-split)."""
        assert resolve_layout("bullets", {"bullets": ["a"] * 6}) == "two_column"

    def test_data_with_3_values_maps_to_chart(self):
        assert resolve_layout("data", {"chart_data": {"labels": ["a", "b", "c"], "values": [1, 2, 3]}}) == "chart"

    def test_data_with_2_values_falls_back_to_bullets(self):
        """Too few data points → bullets instead of chart."""
        result = resolve_layout("data", {"chart_data": {"labels": ["a", "b"], "values": [1, 2]}})
        assert result == "bullets"

    def test_unknown_falls_back_to_title_content(self):
        assert resolve_layout("unknown_type", {}) == "title_content"


# ─── v0.6.2.patch1 two_column fallback tests ──────────────────────────


class TestTwoColumnFallback:
    """v0.6.2.patch1: split flat bullets into left/right when columns empty.

    Bug: LLM returns content_type="comparison" but outputs flat bullets
    list (e.g., "理论机制解析" — single concept, not A vs B). rules.py
    now splits the bullets in half to recover.
    """

    def test_6_bullets_split_in_half(self):
        content = {"bullets": ["a", "b", "c", "d", "e", "f"]}
        out = validate_content_for_layout("bullets", "two_column", content)
        assert out["left"]["items"] == ["a", "b", "c"]
        assert out["right"]["items"] == ["d", "e", "f"]
        assert out["bullets"] == []  # cleared to avoid double-display

    def test_7_bullets_odd_split_left_heavy(self):
        """Odd count: (7+1)//2 = 4, so left gets 4 and right gets 3."""
        content = {"bullets": ["a", "b", "c", "d", "e", "f", "g"]}
        out = validate_content_for_layout("bullets", "two_column", content)
        assert out["left"]["items"] == ["a", "b", "c", "d"]
        assert out["right"]["items"] == ["e", "f", "g"]

    def test_1_bullet_split(self):
        """Edge: 1 bullet goes entirely to left, right is empty."""
        content = {"bullets": ["only"]}
        out = validate_content_for_layout("bullets", "two_column", content)
        assert out["left"]["items"] == ["only"]
        assert out["right"]["items"] == []

    def test_existing_left_right_preserved(self):
        """Normal path (LLM outputs proper left/right) must not be destroyed."""
        content = {
            "left": {"heading": "Pros", "items": ["fast"]},
            "right": {"heading": "Cons", "items": ["slow"]},
            "bullets": ["ignored"],
        }
        out = validate_content_for_layout("comparison", "two_column", content)
        assert out["left"]["items"] == ["fast"]
        assert out["right"]["items"] == ["slow"]
        # bullets NOT cleared when columns are valid
        assert out["bullets"] == ["ignored"]

    def test_partial_left_only_not_triggered(self):
        """Half-filled (one column has items) must NOT trigger fallback."""
        content = {
            "left": {"heading": "A", "items": ["x", "y"]},
            "right": {"heading": "", "items": []},
        }
        out = validate_content_for_layout("comparison", "two_column", content)
        assert out["left"]["items"] == ["x", "y"]
        assert out["right"]["items"] == []
        # Fallback should NOT have fired (left had items)

    def test_partial_right_only_not_triggered(self):
        content = {
            "left": {"heading": "", "items": []},
            "right": {"heading": "B", "items": ["x", "y"]},
        }
        out = validate_content_for_layout("comparison", "two_column", content)
        assert out["right"]["items"] == ["x", "y"]
        assert out["left"]["items"] == []

    def test_completely_empty_two_column(self):
        """Both empty AND no bullets: just normalize to empty dicts."""
        content = {}
        out = validate_content_for_layout("comparison", "two_column", content)
        assert out["left"] == {"heading": "", "items": []}
        assert out["right"] == {"heading": "", "items": []}

    def test_bullets_layout_not_split(self):
        """bullets layout must NOT be affected by the fallback logic."""
        content = {"bullets": ["a", "b", "c"]}
        out = validate_content_for_layout("bullets", "bullets", content)
        assert out["bullets"] == ["a", "b", "c"]
        # No left/right manipulation happened
        assert out.get("left") is None
        assert out.get("right") is None
