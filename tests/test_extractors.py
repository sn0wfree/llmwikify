"""Tests for content extractors."""

import pytest
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.llmwikify import extract, detect_source_type, _extract_text_file, WikiIndex


class TestDetectSourceType:
    """Test source type detection."""
    
    def test_detect_pdf(self):
        assert detect_source_type("file.pdf") == "pdf"
        assert detect_source_type("/path/to/file.PDF") == "pdf"
    
    def test_detect_markdown(self):
        assert detect_source_type("file.md") == "markdown"
        assert detect_source_type("file.txt") == "text"
    
    def test_detect_html(self):
        assert detect_source_type("file.html") == "html"
        assert detect_source_type("file.htm") == "html"
    
    def test_detect_url(self):
        assert detect_source_type("https://example.com/article") == "url"
        assert detect_source_type("http://example.com") == "url"
    
    def test_detect_youtube(self):
        assert detect_source_type("https://youtube.com/watch?v=abc123") == "youtube"
        assert detect_source_type("https://youtu.be/abc123") == "youtube"
        assert detect_source_type("https://youtube.com/embed/abc123") == "youtube"


class TestExtractTextFile:
    """Test text file extraction."""
    
    def test_extract_md(self, temp_wiki):
        """Test markdown extraction."""
        test_file = temp_wiki / "test.md"
        test_file.write_text("# Test Title\n\nContent here")
        
        result = _extract_text_file(test_file)
        
        assert result.source_type == "markdown"
        assert result.title == "Test Title"
        assert "Content here" in result.text
    
    def test_extract_txt(self, temp_wiki):
        """Test plain text extraction."""
        test_file = temp_wiki / "test.txt"
        test_file.write_text("Plain text content")
        
        result = _extract_text_file(test_file)
        
        assert result.source_type == "text"
        assert "Plain text" in result.text


class TestLinkParsing:
    """Test wiki link parsing."""
    
    def test_parse_simple_link(self, temp_wiki):
        content = "Check [[Page Name]] for details"
        db_path = temp_wiki / "test.db"
        index = WikiIndex(db_path)
        links = index._parse_links(content)
        
        assert len(links) == 1
        assert links[0]['target'] == 'Page Name'
        assert links[0]['display'] == 'Page Name'
    
    def test_parse_custom_display(self, temp_wiki):
        content = "See [[page|Custom Text]]"
        db_path = temp_wiki / "test.db"
        index = WikiIndex(db_path)
        links = index._parse_links(content)
        
        assert len(links) == 1
        assert links[0]['target'] == 'page'
        assert links[0]['display'] == 'Custom Text'
    
    def test_parse_section_link(self, temp_wiki):
        content = "Go to [[page#section]]"
        db_path = temp_wiki / "test.db"
        index = WikiIndex(db_path)
        links = index._parse_links(content)
        
        assert len(links) == 1
        assert links[0]['target'] == 'page'
        assert links[0]['section'] == '#section'
    
    def test_parse_full_link(self, temp_wiki):
        content = "Link: [[page#section|Display]]"
        db_path = temp_wiki / "test.db"
        index = WikiIndex(db_path)
        links = index._parse_links(content)
        
        assert len(links) == 1
        assert links[0]['target'] == 'page'
        assert links[0]['section'] == '#section'
        assert links[0]['display'] == 'Display'
    
    def test_parse_multiple_links(self, temp_wiki):
        content = "[[A]] and [[B|Display B]] and [[C#section]]"
        db_path = temp_wiki / "test.db"
        index = WikiIndex(db_path)
        links = index._parse_links(content)
        
        assert len(links) == 3
        targets = [l['target'] for l in links]
        assert 'A' in targets
        assert 'B' in targets
        assert 'C' in targets
