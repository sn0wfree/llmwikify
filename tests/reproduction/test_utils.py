"""Tests for reproduction.utils — slug generation and frontmatter parsing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from llmwikify.reproduction.common.utils import generate_slug, parse_frontmatter

# --- generate_slug tests ---


class TestGenerateSlug:
    def test_basic(self):
        assert generate_slug("My Cool Factor") == "my-cool-factor"

    def test_underscores_to_hyphens(self):
        assert generate_slug("RSI_14-day") == "rsi-14-day"

    def test_strips_special_chars(self):
        assert generate_slug("Factor@#$%!") == "factor"

    def test_collapses_multiple_hyphens(self):
        assert generate_slug("a---b") == "a-b"

    def test_strips_leading_trailing_hyphens(self):
        assert generate_slug("-hello-") == "hello"

    def test_max_80_chars(self):
        long_name = "A" * 100
        assert len(generate_slug(long_name)) == 80

    def test_empty_string(self):
        assert generate_slug("") == ""

    def test_chinese_chars_stripped(self):
        assert generate_slug("动量因子") == ""

    def test_mixed_content(self):
        assert generate_slug("Factor 1 (v2.0)!") == "factor-1-v20"


# --- parse_frontmatter tests ---


class TestParseFrontmatter:
    def test_simple_scalars(self):
        content = "---\ntitle: Hello\nstatus: draft\n---\n\nBody"
        fm = parse_frontmatter(content)
        assert fm["title"] == "Hello"
        assert fm["status"] == "draft"

    def test_list_values(self):
        content = "---\ntags: [alpha, beta, gamma]\n---\n\nBody"
        fm = parse_frontmatter(content)
        assert fm["tags"] == ["alpha", "beta", "gamma"]

    def test_dict_values(self):
        content = "---\nparams: {fast: 5, slow: 20}\n---\n\nBody"
        fm = parse_frontmatter(content)
        assert fm["params"] == {"fast": "5", "slow": "20"}

    def test_no_frontmatter(self):
        content = "Just plain markdown"
        fm = parse_frontmatter(content)
        assert fm == {}

    def test_empty_frontmatter(self):
        content = "---\n---\n\nBody"
        fm = parse_frontmatter(content)
        assert fm == {}

    def test_quoted_values(self):
        content = '---\ntitle: "Hello World"\n---\n\nBody'
        fm = parse_frontmatter(content)
        assert fm["title"] == "Hello World"

    def test_comment_lines_skipped(self):
        content = "---\n# This is a comment\ntitle: Hello\n---\n\nBody"
        fm = parse_frontmatter(content)
        assert "title" in fm
        assert "# This is a comment" not in fm

    def test_factor_frontmatter(self):
        content = """---
title: Momentum Factor
type: Factor
factor_class: momentum
factor_params: {lookback: 20}
signal_type: momentum
signal_params: {period: 20}
status: draft
---

# Momentum Factor
"""
        fm = parse_frontmatter(content)
        assert fm["type"] == "Factor"
        assert fm["factor_class"] == "momentum"
        assert fm["signal_type"] == "momentum"
        assert fm["status"] == "draft"
