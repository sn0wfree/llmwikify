"""Tests for PPTChat Harness, ChatEngine, and ChatRouter."""

import pytest
import json
from llmwikify.apps.ppt.harness import SlideHarness
from llmwikify.apps.ppt.schema import (
    Presentation, SlideContent, Theme, ThemeColors,
)
from llmwikify.apps.ppt.themes import get_theme


# ─── Fixtures ──────────────────────────────────────────────────────

def _make_presentation(slides=None):
    """Create a test Presentation."""
    if slides is None:
        slides = [
            SlideContent(id="s1", layout="title", title="Title Page", subtitle="Subtitle"),
            SlideContent(id="s2", layout="bullets", title="Key Points", bullets=["A", "B", "C"]),
            SlideContent(id="s3", layout="chart", title="Data", chart_type="bar",
                         chart_data={"labels": ["Q1", "Q2"], "values": [10, 20]}),
            SlideContent(id="s4", layout="quote", title="Quote", text="Hello", author="Me"),
        ]
    theme = get_theme("minimal-white")
    return Presentation(
        title="Test Presentation",
        subtitle="Test Subtitle",
        theme=theme,
        slides=slides,
    )


# ─── SlideHarness Tests ───────────────────────────────────────────

class TestSlideHarness:
    def test_delete_slide(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.delete_slide(1)
        assert len(result.slides) == 3
        assert result.slides[0].title == "Title Page"
        assert result.slides[1].title == "Data"  # was index 2

    def test_delete_slide_out_of_range(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.delete_slide(99)
        assert len(result.slides) == 4  # unchanged

    def test_move_slide(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.move_slide(0, 2)
        assert result.slides[0].title == "Key Points"
        assert result.slides[1].title == "Data"
        assert result.slides[2].title == "Title Page"

    def test_move_slide_same_position(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.move_slide(1, 1)
        assert result.slides[1].title == "Key Points"  # unchanged

    def test_duplicate_slide(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.duplicate_slide(1)
        assert len(result.slides) == 5
        assert result.slides[1].title == "Key Points"
        assert result.slides[2].title == "Key Points"  # duplicate
        assert result.slides[2].id == "s2-dup"

    def test_change_theme(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.change_theme("dracula")
        assert result.theme.id == "dracula"

    def test_change_layout(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.change_layout(1, "title_content")
        assert result.slides[1].layout == "title_content"
        assert result.slides[1].bullets is None  # cleared

    def test_undo(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        harness.delete_slide(0)
        assert len(harness.slides) == 3
        result = harness.undo()
        assert len(result.slides) == 4

    def test_undo_empty_history(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        result = harness.undo()
        assert len(result.slides) == 4  # unchanged

    def test_can_undo(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        assert not harness.can_undo()
        harness.delete_slide(0)
        assert harness.can_undo()

    def test_history_limit(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        for i in range(25):
            harness.delete_slide(0)
        assert len(harness.history) == 20  # capped

    def test_slide_count(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        assert harness.slide_count() == 4

    def test_get_slide(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        slide = harness.get_slide(1)
        assert slide is not None
        assert slide.title == "Key Points"
        assert harness.get_slide(99) is None

    def test_to_dict_and_from_dict(self):
        pres = _make_presentation()
        harness = SlideHarness(pres)
        harness.delete_slide(0)
        data = harness.to_dict()
        restored = SlideHarness.from_dict(data, pres)
        assert restored.slide_count() == 3
        assert restored.theme.id == "minimal-white"


# ─── ChatRouter Deterministic Tests ────────────────────────────────

class TestChatRouterPatterns:
    """Test the regex pattern matching in PPTChatRouter."""

    def test_delete_pattern_cn(self):
        from llmwikify.apps.ppt.chat_router import PATTERNS
        import re
        # Get the actual key from the dict
        delete_key = [k for k in PATTERNS if "删除" in k and "幻灯片" in k][0]
        match = re.search(delete_key, "删除第3页")
        assert match is not None
        assert match.group(1) == "3"

    def test_delete_pattern_this(self):
        import re
        from llmwikify.apps.ppt.chat_router import PATTERNS
        delete_key = [k for k in PATTERNS if "删除" in k and "幻灯片" in k][0]
        match = re.search(delete_key, "删除这页")
        assert match is None  # "这页" doesn't have a number

    def test_move_pattern(self):
        import re
        from llmwikify.apps.ppt.chat_router import PATTERNS
        move_key = [k for k in PATTERNS if "移动" in k][0]
        match = re.search(move_key, "移动第2页到第5页")
        assert match is not None
        assert match.group(1) == "2"
        assert match.group(2) == "5"

    def test_duplicate_pattern(self):
        import re
        from llmwikify.apps.ppt.chat_router import PATTERNS
        dup_key = [k for k in PATTERNS if "复制" in k][0]
        match = re.search(dup_key, "复制第3页")
        assert match is not None
        assert match.group(1) == "3"

    def test_undo_pattern(self):
        import re
        from llmwikify.apps.ppt.chat_router import PATTERNS
        undo_key = [k for k in PATTERNS if "撤销" in k][0]
        assert re.search(undo_key, "撤销")
        assert re.search(undo_key, "回退")
        assert re.search(undo_key, "上一步")

    def test_theme_pattern(self):
        import re
        from llmwikify.apps.ppt.chat_router import PATTERNS
        theme_key = [k for k in PATTERNS if "换" in k and "主题" in k][0]
        match = re.search(theme_key, "换个主题为dracula")
        assert match is not None
        assert match.group(1) == "dracula"

    def test_parse_cn_num(self):
        from llmwikify.apps.ppt.chat_router import _parse_cn_num
        assert _parse_cn_num("一") == 1
        assert _parse_cn_num("三") == 3
        assert _parse_cn_num("5") == 5
        assert _parse_cn_num("abc") is None
