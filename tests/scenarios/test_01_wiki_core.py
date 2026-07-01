# tests/scenarios/test_01_wiki_core.py
"""Scenario 1: Wiki Core - No LLM required."""

import pytest


class TestWikiCore:
    """Test core wiki operations: init, ingest, write, search, lint."""

    def test_1_1_init_wiki(self, wiki, temp_dir):
        """Initialize wiki creates expected structure."""
        # create_wiki creates a Wiki instance
        assert wiki is not None
        # Wiki should have root, wiki_dir, raw_dir attributes
        assert hasattr(wiki, "root")
        assert hasattr(wiki, "wiki_dir")
        assert hasattr(wiki, "raw_dir")

    def test_1_2_write_page(self, wiki):
        """Write a page and read it back."""
        content = "# Test Page\n\nThis is a test page with some content."
        wiki.write_page("test-page", content)

        result = wiki.read_page("test-page")
        # read_page returns a dict with 'content' key
        assert isinstance(result, dict)
        assert "Test Page" in result.get("content", "")

    def test_1_3_write_multiple_pages(self, wiki, sample_pages):
        """Write multiple pages."""
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        for name in sample_pages:
            result = wiki.read_page(name)
            assert result is not None
            assert isinstance(result, dict)

    def test_1_4_search(self, wiki, sample_pages):
        """Search returns matching results."""
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        results = wiki.search("Python", limit=10)
        assert len(results) > 0

    def test_1_5_build_index(self, wiki, sample_pages):
        """Build index creates page_links."""
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        idx = wiki.build_index()
        assert "total_pages" in idx
        assert idx["total_pages"] >= 3

    def test_1_6_bidirectional_links(self, wiki):
        """Get inbound and outbound links."""
        wiki.write_page("page-a", "# Page A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# Page B\n\nLinked from [[page-a]].")
        wiki.build_index()

        inbound = wiki.get_inbound_links("page-b")
        assert len(inbound) > 0

        outbound = wiki.get_outbound_links("page-a")
        assert len(outbound) > 0

    def test_1_7_lint(self, wiki, sample_pages):
        """Lint returns issues and hints."""
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        result = wiki.lint()
        assert "issues" in result
        assert "hints" in result

    def test_1_8_status(self, wiki, sample_pages):
        """Status returns statistics."""
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        status = wiki.status()
        assert "page_count" in status or "total_pages" in status
