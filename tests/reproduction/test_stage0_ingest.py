"""Tests for stage0_ingest helper functions and Stage0Result."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.reproduction.paper_understanding.llm_extraction.stage0_ingest import (
    Stage0Result,
    _content_hash,
    _slugify_paper_id,
)


class TestSlugifyPaperId:
    def test_basic_pdf(self):
        assert _slugify_paper_id("1601.00991v3.pdf") == "1601_00991v3"

    def test_simple_name(self):
        assert _slugify_paper_id("my_paper.pdf") == "my_paper"

    def test_with_dots(self):
        assert _slugify_paper_id("paper.v2.final.pdf") == "paper_v2_final"

    def test_with_spaces(self):
        assert _slugify_paper_id("my paper.pdf") == "my_paper"

    def test_multiple_underscores_collapsed(self):
        assert _slugify_paper_id("a___b.pdf") == "a_b"

    def test_strips_leading_trailing_underscores(self):
        assert _slugify_paper_id("_paper_.pdf") == "paper"

    def test_empty_name(self):
        assert _slugify_paper_id("") == "paper"

    def test_only_extension(self):
        # ".pdf" stem is "pdf", which is valid
        assert _slugify_paper_id(".pdf") == "pdf"

    def test_chinese_name(self):
        result = _slugify_paper_id("量化因子.pdf")
        assert result  # Should not be empty
        assert " " not in result


class TestContentHash:
    def test_deterministic(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _content_hash("hello")
        h2 = _content_hash("world")
        assert h1 != h2

    def test_length(self):
        h = _content_hash("test")
        assert len(h) == 16

    def test_hex_chars(self):
        h = _content_hash("test")
        assert all(c in "0123456789abcdef" for c in h)

    def test_unicode(self):
        h = _content_hash("量化因子")
        assert len(h) == 16


class TestStage0Result:
    def test_creation(self, tmp_path):
        r = Stage0Result(
            paper_id="test",
            source_path=tmp_path / "test.pdf",
            parsed_md_path=tmp_path / "parsed.md",
            text="hello",
            title="Test",
            source_type="pdf",
        )
        assert r.paper_id == "test"
        assert r.char_count == 0  # default

    def test_to_dict(self, tmp_path):
        r = Stage0Result(
            paper_id="test",
            source_path=tmp_path / "test.pdf",
            parsed_md_path=tmp_path / "parsed.md",
            text="hello",
            title="Test",
            source_type="pdf",
            char_count=5,
            content_hash="abc123",
        )
        d = r.to_dict()
        assert d["paper_id"] == "test"
        assert d["char_count"] == 5
        assert d["content_hash"] == "abc123"
        assert isinstance(d["source_path"], str)

    def test_to_dict_with_metadata(self, tmp_path):
        r = Stage0Result(
            paper_id="test",
            source_path=tmp_path / "test.pdf",
            parsed_md_path=tmp_path / "parsed.md",
            text="hello",
            title="Test",
            source_type="pdf",
            metadata={"cached": True, "pages": 10},
        )
        d = r.to_dict()
        assert d["metadata"]["cached"] is True
        assert d["metadata"]["pages"] == 10

    def test_defaults(self, tmp_path):
        r = Stage0Result(
            paper_id="test",
            source_path=tmp_path / "test.pdf",
            parsed_md_path=tmp_path / "parsed.md",
            text="",
            title="",
            source_type="unknown",
        )
        assert r.metadata == {}
        assert r.char_count == 0
        assert r.content_hash == ""
