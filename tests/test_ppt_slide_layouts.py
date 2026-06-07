"""Tests for extended SlideContent layout types and serialization."""

import json
import pytest
from llmwikify.apps.ppt.schema import SlideContent, Presentation
from llmwikify.apps.ppt.themes import get_theme


def _make_slide(**overrides):
    defaults = {"id": "test-1", "layout": "bullets", "title": "Test"}
    defaults.update(overrides)
    return SlideContent(**defaults)


# ─── Schema field tests ────────────────────────────────────────

class TestSlideContentFields:
    def test_swot_field(self):
        slide = _make_slide(
            layout="swot",
            swot={"strengths": ["S1"], "weaknesses": ["W1"], "opportunities": ["O1"], "threats": ["T1"]},
        )
        assert slide.swot is not None
        assert len(slide.swot["strengths"]) == 1

    def test_table_fields(self):
        slide = _make_slide(
            layout="table",
            table_headers=["Name", "Value"],
            table_rows=[["A", "1"], ["B", "2"]],
        )
        assert slide.table_headers == ["Name", "Value"]
        assert len(slide.table_rows) == 2

    def test_timeline_fields(self):
        slide = _make_slide(
            layout="timeline",
            events=[{"date": "2024-01", "title": "Event 1", "description": "Desc"}],
        )
        assert len(slide.events) == 1
        assert slide.events[0]["date"] == "2024-01"

    def test_kpi_fields(self):
        slide = _make_slide(
            layout="kpi_grid",
            kpi_items=[{"label": "Revenue", "value": "$1M", "trend": "+10%"}],
        )
        assert len(slide.kpi_items) == 1
        assert slide.kpi_items[0]["trend"] == "+10%"

    def test_mindmap_fields(self):
        slide = _make_slide(
            layout="mindmap",
            central_topic="Main Topic",
            branches=[{"name": "Branch 1", "children": [{"name": "Sub 1"}]}],
        )
        assert slide.central_topic == "Main Topic"
        assert len(slide.branches) == 1

    def test_process_fields(self):
        slide = _make_slide(
            layout="process",
            steps=[{"title": "Step 1", "description": "Do something"}],
        )
        assert len(slide.steps) == 1

    def test_gallery_fields(self):
        slide = _make_slide(
            layout="gallery",
            images=[{"url": "http://example.com/img.jpg", "caption": "Photo"}],
        )
        assert len(slide.images) == 1

    def test_html_field(self):
        slide = _make_slide(layout="html", html="<div>Custom</div>")
        assert slide.html == "<div>Custom</div>"

    def test_image_text_fields(self):
        slide = _make_slide(layout="image_text", image="http://img.jpg", content="Description")
        assert slide.image == "http://img.jpg"
        assert slide.content == "Description"


# ─── Serialization tests ──────────────────────────────────────

class TestSlideSerialization:
    def test_swot_roundtrip(self):
        original = _make_slide(
            layout="swot",
            swot={"strengths": ["S1", "S2"], "weaknesses": ["W1"], "opportunities": ["O1"], "threats": ["T1", "T2"]},
        )
        data = original.model_dump()
        restored = SlideContent(**data)
        assert restored.swot == original.swot

    def test_all_fields_roundtrip(self):
        original = _make_slide(
            layout="custom",
            swot={"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            table_headers=["H1"],
            table_rows=[["R1"]],
            events=[{"date": "2024", "title": "E"}],
            kpi_items=[{"label": "K", "value": "V"}],
            central_topic="Topic",
            branches=[{"name": "B"}],
            steps=[{"title": "S"}],
            images=[{"url": "u", "caption": "c"}],
            html="<div>HTML</div>",
        )
        data = original.model_dump()
        json_str = json.dumps(data, ensure_ascii=False)
        restored = SlideContent(**json.loads(json_str))
        assert restored.swot is not None
        assert restored.table_headers == ["H1"]
        assert restored.html == "<div>HTML</div>"

    def test_optional_fields_default_none(self):
        slide = _make_slide()
        assert slide.swot is None
        assert slide.table_headers is None
        assert slide.events is None
        assert slide.html is None


# ─── Presentation with extended layouts ────────────────────────

class TestPresentationExtendedLayouts:
    def test_presentation_with_swot_slide(self):
        pres = Presentation(
            title="Test",
            theme=get_theme("minimal-white"),
            slides=[
                _make_slide(layout="swot", swot={"strengths": ["S"], "weaknesses": [], "opportunities": [], "threats": []}),
            ],
        )
        data = pres.model_dump()
        restored = Presentation(**data)
        assert restored.slides[0].layout == "swot"
        assert restored.slides[0].swot["strengths"] == ["S"]

    def test_presentation_mixed_layouts(self):
        pres = Presentation(
            title="Mixed",
            theme=get_theme("minimal-white"),
            slides=[
                _make_slide(id="s1", layout="title"),
                _make_slide(id="s2", layout="swot", swot={"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}),
                _make_slide(id="s3", layout="table", table_headers=["A"], table_rows=[["B"]]),
                _make_slide(id="s4", layout="html", html="<p>Hi</p>"),
            ],
        )
        assert len(pres.slides) == 4
        assert pres.slides[1].swot is not None
        assert pres.slides[2].table_headers == ["A"]
        assert pres.slides[3].html == "<p>Hi</p>"
