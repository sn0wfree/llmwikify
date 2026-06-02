"""Tests for PPT prompt templates — v0.6.2.patch1.

Covers:
- Prompt template integrity (all placeholders present)
- Language routing helper (zh path, en TODO fallback)
- Content prompt content includes the critical comparison vs bullets
  boundary rules (regression guard for the "理论机制解析" bug)
"""

import pytest

from llmwikify.agent.backend.ppt.engine import (
    CONTENT_PROMPT_ZH,
    OUTLINE_PROMPT_ZH,
    RESEARCH_OUTLINE_PROMPT_ZH,
    CHAT_OUTLINE_PROMPT_ZH,
    get_content_prompt,
    get_outline_prompt,
    get_research_prompt,
    get_chat_prompt,
)


# ─── Template integrity ────────────────────────────────────────────────


class TestPromptPlaceholders:
    """All required .format() placeholders must be present."""

    def test_content_prompt_has_all_placeholders(self):
        # Should not raise KeyError on .format(...)
        rendered = CONTENT_PROMPT_ZH.format(
            title="T", page_num=1, total_pages=5,
            content_type="bullets", slide_title="S", slide_description="D",
        )
        assert "T" in rendered
        assert "1" in rendered
        assert "5" in rendered
        assert "bullets" in rendered
        assert "S" in rendered
        assert "D" in rendered

    def test_outline_prompt_has_all_placeholders(self):
        rendered = OUTLINE_PROMPT_ZH.format(topic="AI risk", num_slides=5)
        assert "AI risk" in rendered
        assert "5" in rendered

    def test_research_prompt_has_all_placeholders(self):
        rendered = RESEARCH_OUTLINE_PROMPT_ZH.format(
            topic="T", summary="S", findings="F", source_count=3,
        )
        assert "T" in rendered and "S" in rendered
        assert "F" in rendered and "3" in rendered

    def test_chat_prompt_has_all_placeholders(self):
        rendered = CHAT_OUTLINE_PROMPT_ZH.format(
            topic="T", summary="S", key_points="K", message_count=10,
        )
        assert "T" in rendered and "K" in rendered
        assert "10" in rendered


# ─── Language routing ──────────────────────────────────────────────────


class TestLanguageRouting:
    """v0.6.2.patch1: helpers route by language, en returns TODO marker."""

    def test_get_content_prompt_zh_returns_chinese(self):
        out = get_content_prompt(
            language="zh",
            title="T", page_num=1, total_pages=5,
            content_type="bullets", slide_title="S", slide_description="D",
        )
        # TODO marker must NOT appear in zh path
        assert "TODO" not in out
        # Chinese keywords present
        assert "演示" in out or "类型" in out

    def test_get_content_prompt_en_falls_back_to_zh_with_todo(self):
        out = get_content_prompt(
            language="en",
            title="T", page_num=1, total_pages=5,
            content_type="bullets", slide_title="S", slide_description="D",
        )
        # en path returns Chinese + TODO marker (per Q6: keep Chinese only)
        assert "TODO" in out
        assert "v0.6.3" in out  # version-tagged TODO

    def test_get_outline_prompt_zh(self):
        out = get_outline_prompt(language="zh", topic="AI", num_slides=3)
        assert "AI" in out
        assert "TODO" not in out

    def test_get_outline_prompt_en_fallback(self):
        out = get_outline_prompt(language="en", topic="AI", num_slides=3)
        assert "TODO" in out

    def test_get_research_prompt_zh(self):
        out = get_research_prompt(
            language="zh", topic="T", summary="S", findings="F", source_count=1,
        )
        assert "TODO" not in out

    def test_get_chat_prompt_zh(self):
        out = get_chat_prompt(
            language="zh", topic="T", summary="S", key_points="K", message_count=1,
        )
        assert "TODO" not in out


# ─── Content quality (regression guard) ───────────────────────────────


class TestContentPromptQuality:
    """Verify v0.6.2.patch1 critical rules are present in CONTENT prompt.

    Regression guard: if someone weakens the prompt without thinking,
    these tests fail. Specifically the "理论机制解析" bug must not
    recur — the prompt must explicitly forbid comparison→bullets fallback.
    """

    def test_comparison_vs_bullets_boundary_present(self):
        """The exact section that fixed the screenshot bug."""
        assert "comparison" in CONTENT_PROMPT_ZH
        # Must contain a "when NOT to use comparison" rule
        assert "不要" in CONTENT_PROMPT_ZH or "何时" in CONTENT_PROMPT_ZH

    def test_must_output_left_right_for_comparison(self):
        """The '禁止回退为 bullets' rule for comparison type."""
        assert "left/right" in CONTENT_PROMPT_ZH or "left" in CONTENT_PROMPT_ZH and "right" in CONTENT_PROMPT_ZH

    def test_no_markdown_wrap_warning_present(self):
        """The prompt must warn against ```json wrapping."""
        assert "```" in CONTENT_PROMPT_ZH

    def test_self_check_section_present(self):
        """The ✓ self-check list must be in the prompt."""
        assert "自检" in CONTENT_PROMPT_ZH

    def test_anti_patterns_section_present(self):
        """The ❌ anti-patterns list must be in the prompt."""
        assert "❌" in CONTENT_PROMPT_ZH

    def test_role_framing_is_senior(self):
        """The role should be '10 年' senior designer, not 'assistant'."""
        # Old prompt: "你是一个专业的演示文稿内容生成助手"
        # New prompt: "你是一位资深演示文稿内容设计师（10 年咨询/演讲经验）"
        assert "10 年" in CONTENT_PROMPT_ZH or "资深" in CONTENT_PROMPT_ZH
