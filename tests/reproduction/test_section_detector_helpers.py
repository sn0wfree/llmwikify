"""Tests for section_detector helper functions and dataclasses."""
from __future__ import annotations

import pytest

from llmwikify.reproduction.paper_understanding.llm_extraction.section_detector import (
    Section,
    SectionDetectionResult,
    _extract_json,
    _parse_sections,
)


class TestExtractJson:
    def test_valid_json(self):
        result = _extract_json('{"sections": []}')
        assert result == {"sections": []}

    def test_json_in_markdown(self):
        result = _extract_json('```json\n{"sections": []}\n```')
        assert result == {"sections": []}

    def test_json_with_surrounding_text(self):
        result = _extract_json('Here is the result: {"sections": []} done.')
        assert result == {"sections": []}

    def test_no_json(self):
        result = _extract_json("no json here")
        assert result is None

    def test_truncated_json_returns_none(self):
        # Truncated JSON that can't be repaired returns None
        result = _extract_json('{"sections": [{"id": 1, "title": "Intro"')
        assert result is None


class TestParseSections:
    def test_empty_data(self):
        result = _parse_sections({}, 1000)
        assert result == []

    def test_empty_sections_list(self):
        result = _parse_sections({"sections": []}, 1000)
        assert result == []

    def test_valid_section(self):
        data = {
            "sections": [
                {"id": 1, "title": "Introduction", "level": 1, "char_start": 0, "char_end": 500}
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 1
        assert result[0].title == "Introduction"
        assert result[0].level == 1

    def test_multiple_sections(self):
        data = {
            "sections": [
                {"id": 1, "title": "Intro", "level": 1, "char_start": 0, "char_end": 100},
                {"id": 2, "title": "Method", "level": 2, "char_start": 100, "char_end": 200},
                {"id": 3, "title": "Results", "level": 2, "char_start": 200, "char_end": 300},
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 3

    def test_skips_empty_title(self):
        data = {
            "sections": [
                {"id": 1, "title": "", "level": 1, "char_start": 0, "char_end": 100},
                {"id": 2, "title": "Valid", "level": 1, "char_start": 100, "char_end": 200},
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 1
        assert result[0].title == "Valid"

    def test_skips_duplicate_ids(self):
        data = {
            "sections": [
                {"id": 1, "title": "First", "level": 1, "char_start": 0, "char_end": 100},
                {"id": 1, "title": "Duplicate", "level": 1, "char_start": 100, "char_end": 200},
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 1

    def test_level_clamped_to_1_3(self):
        data = {
            "sections": [
                {"id": 1, "title": "Low", "level": 0, "char_start": 0, "char_end": 100},
                {"id": 2, "title": "High", "level": 5, "char_start": 100, "char_end": 200},
            ]
        }
        result = _parse_sections(data, 1000)
        assert result[0].level == 1  # Clamped to 1
        assert result[1].level == 3  # Clamped to 3

    def test_char_end_clamped_to_text_len(self):
        data = {
            "sections": [
                {"id": 1, "title": "Section", "level": 1, "char_start": 0, "char_end": 2000}
            ]
        }
        result = _parse_sections(data, 1000)
        assert result[0].char_end == 1000

    def test_skips_zero_length_section(self):
        data = {
            "sections": [
                {"id": 1, "title": "Empty", "level": 1, "char_start": 100, "char_end": 100}
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 0

    def test_sorted_by_char_start(self):
        data = {
            "sections": [
                {"id": 3, "title": "Last", "level": 1, "char_start": 300, "char_end": 400},
                {"id": 1, "title": "First", "level": 1, "char_start": 0, "char_end": 100},
                {"id": 2, "title": "Middle", "level": 1, "char_start": 100, "char_end": 200},
            ]
        }
        result = _parse_sections(data, 1000)
        assert result[0].title == "First"
        assert result[1].title == "Middle"
        assert result[2].title == "Last"

    def test_ids_renumbered_after_sort(self):
        data = {
            "sections": [
                {"id": 5, "title": "Last", "level": 1, "char_start": 300, "char_end": 400},
                {"id": 1, "title": "First", "level": 1, "char_start": 0, "char_end": 100},
            ]
        }
        result = _parse_sections(data, 1000)
        assert result[0].id == 1
        assert result[1].id == 2

    def test_invalid_values_skipped(self):
        data = {
            "sections": [
                {"id": "not_a_number", "title": "Bad", "level": 1, "char_start": 0, "char_end": 100},
                {"id": 2, "title": "Good", "level": 1, "char_start": 0, "char_end": 100},
            ]
        }
        result = _parse_sections(data, 1000)
        assert len(result) == 1


class TestSection:
    def test_to_dict(self):
        s = Section(id=1, title="Intro", level=1, char_start=0, char_end=500)
        d = s.to_dict()
        assert d["id"] == 1
        assert d["title"] == "Intro"
        assert d["level"] == 1
        assert d["char_start"] == 0
        assert d["char_end"] == 500


class TestSectionDetectionResult:
    def test_defaults(self):
        r = SectionDetectionResult(paper_id="test")
        assert r.sections == []
        assert r.n_sections == 0
        assert r.success is False

    def test_to_dict(self):
        r = SectionDetectionResult(
            paper_id="test",
            sections=[Section(id=1, title="Intro", level=1, char_start=0, char_end=100)],
            n_sections=1,
            latency_ms=100,
            success=True,
        )
        d = r.to_dict()
        assert d["paper_id"] == "test"
        assert d["n_sections"] == 1
        assert len(d["sections"]) == 1
        assert d["success"] is True
