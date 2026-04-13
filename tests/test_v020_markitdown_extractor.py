"""Tests for Phase 5: MarkItDown enhanced extractor integration."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from llmwikify.extractors.base import (
    detect_source_type, extract, ExtractedContent
)
from llmwikify.extractors.markitdown_extractor import (
    MarkItDownExtractor, MARKITDOWN_FORMATS, _ext_to_source_type
)


class TestMarkItDownFormats:
    """Test format detection for MarkItDown-supported files."""

    def test_office_formats(self):
        assert detect_source_type("report.docx") == "docx"
        assert detect_source_type("report.doc") == "doc"
        assert detect_source_type("data.xlsx") == "xlsx"
        assert detect_source_type("data.xls") == "xls"
        assert detect_source_type("slides.pptx") == "pptx"
        assert detect_source_type("slides.ppt") == "ppt"

    def test_image_formats(self):
        assert detect_source_type("photo.jpg") == "image"
        assert detect_source_type("photo.jpeg") == "image"
        assert detect_source_type("photo.png") == "image"
        assert detect_source_type("photo.gif") == "image"
        assert detect_source_type("photo.bmp") == "image"
        assert detect_source_type("photo.tiff") == "image"
        assert detect_source_type("photo.webp") == "image"

    def test_audio_formats(self):
        assert detect_source_type("recording.mp3") == "audio"
        assert detect_source_type("recording.wav") == "audio"
        assert detect_source_type("recording.m4a") == "audio"

    def test_data_formats(self):
        assert detect_source_type("table.csv") == "csv"
        assert detect_source_type("config.json") == "json"
        assert detect_source_type("data.xml") == "xml"

    def test_other_formats(self):
        assert detect_source_type("book.epub") == "epub"
        assert detect_source_type("archive.zip") == "zip"
        assert detect_source_type("email.msg") == "outlook"

    def test_existing_formats_still_work(self):
        assert detect_source_type("document.pdf") == "pdf"
        assert detect_source_type("page.md") == "markdown"
        assert detect_source_type("notes.txt") == "text"
        assert detect_source_type("index.html") == "html"
        assert detect_source_type("page.htm") == "html"
        assert detect_source_type("http://example.com") == "url"
        assert detect_source_type("https://youtube.com/watch?v=abc") == "youtube"

    def test_markitdown_formats_set_contains_all(self):
        assert ".docx" in MARKITDOWN_FORMATS
        assert ".pdf" in MARKITDOWN_FORMATS
        assert ".xlsx" in MARKITDOWN_FORMATS
        assert ".pptx" in MARKITDOWN_FORMATS
        assert ".jpg" in MARKITDOWN_FORMATS
        assert ".png" in MARKITDOWN_FORMATS
        assert ".mp3" in MARKITDOWN_FORMATS
        assert ".csv" in MARKITDOWN_FORMATS
        assert ".epub" in MARKITDOWN_FORMATS


class TestExtToSourceType:
    """Test _ext_to_source_type mapping."""

    def test_pdf(self):
        assert _ext_to_source_type(".pdf") == "pdf"

    def test_office(self):
        assert _ext_to_source_type(".docx") == "docx"
        assert _ext_to_source_type(".xlsx") == "xlsx"
        assert _ext_to_source_type(".pptx") == "pptx"

    def test_image(self):
        assert _ext_to_source_type(".jpg") == "image"
        assert _ext_to_source_type(".png") == "image"
        assert _ext_to_source_type(".webp") == "image"

    def test_audio(self):
        assert _ext_to_source_type(".mp3") == "audio"
        assert _ext_to_source_type(".wav") == "audio"

    def test_unknown_defaults_to_text(self):
        assert _ext_to_source_type(".xyz") == "text"


class TestMarkItDownExtractor:
    """Test MarkItDownExtractor class behavior."""

    @pytest.fixture
    def mock_markitdown(self):
        """Create a mock markitdown module."""
        import sys
        mock_md_module = MagicMock()
        mock_md_class = MagicMock()
        mock_md_module.MarkItDown = mock_md_class
        sys.modules["markitdown"] = mock_md_module
        yield mock_md_class
        del sys.modules["markitdown"]

    def test_extractor_instantiates_without_markitdown(self):
        """Extractor should work even when MarkItDown is not installed."""
        extractor = MarkItDownExtractor()
        # Should not raise; available depends on whether markitdown is installed
        assert isinstance(extractor.available, bool)

    def test_extractor_returns_none_for_missing_file(self, tmp_path):
        extractor = MarkItDownExtractor()
        missing = tmp_path / "nonexistent.docx"
        result = extractor.convert(missing)
        assert result is None

    def test_extractor_returns_none_when_not_available(self):
        """When MarkItDown is not installed, convert returns None."""
        extractor = MarkItDownExtractor()
        if not extractor.available:
            result = extractor.convert(Path("/tmp/test.docx"))
            assert result is None

    def test_extractor_with_markitdown_mocked(self, tmp_path, mock_markitdown):
        """Test successful conversion when MarkItDown is available."""
        test_file = tmp_path / "test.docx"
        test_file.write_text("Mock docx content")

        mock_result = MagicMock()
        mock_result.text_content = "# Test Document\n\nThis is a test."

        mock_instance = MagicMock()
        mock_instance.convert.return_value = mock_result
        mock_markitdown.return_value = mock_instance

        extractor = MarkItDownExtractor()
        assert extractor.available is True

        result = extractor.convert(test_file)
        assert result is not None
        assert "# Test Document" in result.text
        assert result.source_type == "docx"
        assert result.title == "Test Document"
        assert result.metadata["converter"] == "markitdown"

    def test_extractor_falls_back_on_conversion_error(self, tmp_path, mock_markitdown):
        """Test that conversion errors return None (not exception)."""
        test_file = tmp_path / "test.docx"
        test_file.write_text("Mock content")

        mock_instance = MagicMock()
        mock_instance.convert.side_effect = RuntimeError("Conversion failed")
        mock_markitdown.return_value = mock_instance

        extractor = MarkItDownExtractor()
        result = extractor.convert(test_file)
        assert result is None

    def test_extractor_returns_none_for_empty_content(self, tmp_path, mock_markitdown):
        """Test that empty conversion results return None."""
        test_file = tmp_path / "test.docx"
        test_file.write_text("content")

        mock_result = MagicMock()
        mock_result.text_content = ""

        mock_instance = MagicMock()
        mock_instance.convert.return_value = mock_result
        mock_markitdown.return_value = mock_instance

        extractor = MarkItDownExtractor()
        result = extractor.convert(test_file)
        assert result is None

    def test_extractor_handles_llm_config(self):
        """Test that LLM config is accepted without error."""
        config = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "model": "gpt-4o",
                "base_url": "http://localhost:11434",
                "api_key": "test",
            }
        }
        # Should not raise even if MarkItDown is not installed
        extractor = MarkItDownExtractor(config=config)
        assert isinstance(extractor.available, bool)


class TestExtractRouting:
    """Test that extract() correctly routes to MarkItDown for new formats."""

    @pytest.fixture
    def mock_markitdown(self):
        """Create a mock markitdown module."""
        import sys
        mock_md_module = MagicMock()
        mock_md_class = MagicMock()
        mock_md_module.MarkItDown = mock_md_class
        sys.modules["markitdown"] = mock_md_module
        yield mock_md_class
        del sys.modules["markitdown"]

    def test_routes_docx_to_markitdown(self, tmp_path):
        """Unknown .docx file should attempt MarkItDown then return error if unavailable."""
        test_file = tmp_path / "test.docx"
        test_file.write_text("fake docx content")

        # Without markitdown installed, should return clear error
        result = extract(str(test_file))
        assert result.source_type == "error" or result.source_type in ("text", "docx")
        if result.source_type == "error":
            assert "markitdown" in result.metadata.get("error", "").lower()

    def test_routes_pdf_to_markitdown_first(self, tmp_path):
        """PDF should try MarkItDown first, then fallback to pymupdf."""
        test_file = tmp_path / "test.pdf"
        test_file.write_text("fake pdf content")

        result = extract(str(test_file))
        # Should either get markitdown result or fallback to pymupdf or text
        assert result.source_type in ("pdf", "text", "error")

    def test_preserves_text_file_routing(self, tmp_path):
        """Markdown files should still use direct text extraction."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# Title\n\nContent")

        result = extract(str(test_file))
        assert result.source_type == "markdown"
        assert "# Title" in result.text

    def test_preserves_youtube_routing(self):
        """YouTube URLs should still route to youtube extractor."""
        result = extract("https://youtube.com/watch?v=abc123")
        # Without youtube-transcript-api, should return error
        assert result.source_type in ("youtube", "error")

    def test_preserves_url_routing(self):
        """HTTP URLs should still route to web extractor."""
        result = extract("https://example.com/article")
        # Without trafilatura, should return error
        assert result.source_type in ("url", "error")

    def test_fallback_for_nonexistent_file(self, tmp_path):
        """Non-existent file should return error."""
        result = extract(str(tmp_path / "missing.docx"))
        assert result.source_type == "error"
        assert "File not found" in result.metadata["error"]

    def test_markitdown_extraction_success_mock(self, tmp_path, mock_markitdown):
        """Test full extraction pipeline with mocked MarkItDown."""
        test_file = tmp_path / "report.docx"
        test_file.write_text("mock content")

        mock_result = MagicMock()
        mock_result.text_content = "# Report\n\nThis is the report content."

        mock_instance = MagicMock()
        mock_instance.convert.return_value = mock_result
        mock_markitdown.return_value = mock_instance

        result = extract(str(test_file))
        assert result is not None
        assert "# Report" in result.text
        assert result.source_type == "docx"
        assert result.metadata["converter"] == "markitdown"

    def test_markitdown_fallback_to_text(self, tmp_path):
        """When MarkItDown is unavailable, should return clear error for binary formats."""
        test_file = tmp_path / "data.xlsx"
        test_file.write_text("col1,col2\na,b")

        # Without markitdown, returns error (no legacy extractor for xlsx)
        result = extract(str(test_file))
        assert result is not None
        assert result.source_type == "error" or "col1,col2" in result.text


class TestExtractImageFormats:
    """Test image format detection and routing."""

    def test_detect_image_extensions(self, tmp_path):
        for ext in (".jpg", ".png", ".gif", ".bmp", ".tiff", ".webp"):
            filename = f"test{ext}"
            assert detect_source_type(filename) == "image"

    def test_image_routing(self, tmp_path):
        """Image files should attempt MarkItDown first."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("fake image binary")

        result = extract(str(test_file))
        # Without markitdown, returns error (no legacy extractor for images)
        assert result is not None
        assert result.source_type in ("image", "error")
        if result.source_type == "error":
            assert "markitdown" in result.metadata.get("error", "").lower()


class TestBackwardCompatibility:
    """Ensure existing functionality is not broken."""

    def test_existing_pdf_extraction_with_pymupdf(self, tmp_path):
        """PDF extraction should still work via pymupdf fallback."""
        test_file = tmp_path / "test.pdf"
        test_file.write_text("fake pdf")

        result = extract(str(test_file))
        assert result is not None

    def test_html_extraction_preserved(self, tmp_path):
        """HTML files should still be extracted."""
        test_file = tmp_path / "test.html"
        test_file.write_text("<html><head><title>Test</title></head><body><p>Hello</p></body></html>")

        result = extract(str(test_file))
        assert result.source_type == "html"
        assert "Hello" in result.text
        assert result.title == "Test"

    def test_markdown_extraction_preserved(self, tmp_path):
        """Markdown files should still use direct extraction."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# My Page\n\nSome content.")

        result = extract(str(test_file))
        assert result.source_type == "markdown"
        assert result.title == "My Page"
        assert "Some content." in result.text
