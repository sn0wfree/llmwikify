"""Tests for v0.29.0 index enhancement: summaries, grouping, lint integration."""

import json
import tempfile
from pathlib import Path

import pytest

from src.llmwikify.core.wiki import Wiki


@pytest.fixture
def test_wiki():
    """Create a temporary wiki with various page types."""
    tmp = Path(tempfile.mkdtemp())
    wiki = Wiki(tmp)
    wiki.init(agent='generic')
    return wiki, tmp


class TestExtractPageSummary:
    """Test _extract_page_summary method."""

    def test_from_frontmatter_summary(self, test_wiki):
        """Priority 1: Extract summary from YAML frontmatter."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Test Concept.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "---\ntitle: Test Concept\nsummary: This is a frontmatter summary.\n---\n\n# Test Concept\n\nSome content here."
        )
        result = wiki._extract_page_summary(page)
        assert result == "This is a frontmatter summary."

    def test_from_summary_section(self, test_wiki):
        """Priority 2: Extract from ## Summary section (Source pages)."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "sources" / "Test Source.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "# Test Source\n\n## Summary\nThis is the summary section first paragraph.\n\nSome more text.\n\n## Key Entities\n..."
        )
        result = wiki._extract_page_summary(page)
        assert result == "This is the summary section first paragraph."

    def test_from_first_paragraph(self, test_wiki):
        """Priority 3: Extract first paragraph after title."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "entities" / "Test Entity.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Test Entity\n\nThis is the first paragraph after the title.\n\nMore content.")
        result = wiki._extract_page_summary(page)
        assert result == "This is the first paragraph after the title."

    def test_fallback_to_title(self, test_wiki):
        """Priority 4: Fallback to page title."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Empty Page.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Empty Page")
        result = wiki._extract_page_summary(page)
        assert result == "Empty Page"

    def test_truncation(self, test_wiki):
        """Summaries longer than max_len should be truncated."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Long Page.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        long_text = "A" * 150
        page.write_text(f"# Long Page\n\n{long_text}")
        result = wiki._extract_page_summary(page, max_len=120)
        assert len(result) <= 120
        assert result.endswith("...")

    def test_strips_markdown_artifacts(self, test_wiki):
        """Should strip ** and ` from extracted text."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Markdown Page.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Markdown Page\n\nThis is **bold** and `code` text.")
        result = wiki._extract_page_summary(page)
        assert "**" not in result
        assert "`" not in result
        assert "bold" in result
        assert "code" in result

    def test_skips_html_comments(self, test_wiki):
        """Should skip HTML comment lines."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Comment Page.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Comment Page\n\n<!-- some comment -->\n\nActual content here.")
        result = wiki._extract_page_summary(page)
        assert result == "Actual content here."

    def test_empty_file_returns_title(self, test_wiki):
        """Empty file should return page stem as fallback."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "concepts" / "Blank.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("")
        result = wiki._extract_page_summary(page)
        assert result == "Blank"


class TestGetSourceAnalysisSummary:
    """Test _get_source_analysis_summary method."""

    def test_returns_none_without_cache(self, test_wiki):
        """Returns None when no cached analysis exists."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "sources" / "Uncached.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Uncached Source\n\n## Summary\nNo analysis here.")
        result = wiki._get_source_analysis_summary(page)
        assert result is None

    def test_returns_topics_and_entities(self, test_wiki):
        """Returns topics and entities from cached analysis."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "sources" / "Cached.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        analysis_json = json.dumps({
            "topics": ["AI", "Machine Learning"],
            "entities": [{"name": "DeepMind", "type": "organization"}],
        })
        comment = f'<!-- llmwikify:analysis {{"version":1,"hash":"abc","analyzed_at":"2026-01-01","data":{analysis_json}}} -->'
        page.write_text(f"# Cached Source\n\n## Summary\nTest.\n\n{comment}")
        result = wiki._get_source_analysis_summary(page)
        assert result is not None
        assert result["topics"] == ["AI", "Machine Learning"]
        assert result["entities"] == ["DeepMind"]


class TestUpdateIndexFile:
    """Test _update_index_file method."""

    def test_groups_pages_by_type(self, test_wiki):
        """Index should group pages by directory type."""
        wiki, tmp = test_wiki
        # Create pages of different types
        (wiki.wiki_dir / "sources" / "Source A.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "sources" / "Source A.md").write_text("# Source A\n\nA summary of source A.")
        (wiki.wiki_dir / "concepts" / "Concept B.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "concepts" / "Concept B.md").write_text("# Concept B\n\nA concept about B.")
        (wiki.wiki_dir / "entities" / "Entity C.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "entities" / "Entity C.md").write_text("# Entity C\n\nAn entity named C.")

        wiki._update_index_file()
        content = wiki.index_file.read_text()

        assert "## Sources (1)" in content
        assert "## Concepts (1)" in content
        assert "## Entities (1)" in content
        assert "[[sources/Source A]]" in content
        assert "[[concepts/Concept B]]" in content
        assert "[[entities/Entity C]]" in content

    def test_includes_summaries(self, test_wiki):
        """Each page entry should include a summary."""
        wiki, tmp = test_wiki
        (wiki.wiki_dir / "concepts" / "Test.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "concepts" / "Test.md").write_text("# Test\n\nThis is a test page summary for indexing.")

        wiki._update_index_file()
        content = wiki.index_file.read_text()

        assert "This is a test page summary for indexing" in content

    def test_shows_total_and_type_counts(self, test_wiki):
        """Index header should show total and per-type counts."""
        wiki, tmp = test_wiki
        (wiki.wiki_dir / "concepts" / "A.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "concepts" / "A.md").write_text("# A\n\nContent A.")
        (wiki.wiki_dir / "concepts" / "B.md").write_text("# B\n\nContent B.")

        wiki._update_index_file()
        content = wiki.index_file.read_text()

        # Includes 2 concepts + overview.md from init
        assert "Concepts: 2" in content
        assert "[[concepts/A]]" in content
        assert "[[concepts/B]]" in content

    def test_empty_wiki_shows_placeholder(self, test_wiki):
        """Wiki with only overview.md should still show it grouped."""
        wiki, tmp = test_wiki
        wiki._update_index_file()
        content = wiki.index_file.read_text()
        # overview.md is created by init, so it should appear
        assert "## Overview (1)" in content
        assert "[[overview]]" in content

    def test_sink_section_preserved(self, test_wiki):
        """Sink entries should still appear in their own section."""
        wiki, tmp = test_wiki
        sink_dir = wiki.wiki_dir / ".sink"
        sink_dir.mkdir(parents=True, exist_ok=True)
        (sink_dir / "test.sink.md").write_text(
            "## [2026-01-01 12:00:00] Test entry\n\nSome pending update."
        )

        wiki._update_index_file()
        content = wiki.index_file.read_text()

        assert "## Pending Sink Buffers" in content
        assert "[[test]]" in content

    def test_source_page_shows_analysis(self, test_wiki):
        """Source pages with cached analysis should show topics/entities."""
        wiki, tmp = test_wiki
        page = wiki.wiki_dir / "sources" / "Analyzed.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        analysis_json = json.dumps({
            "topics": ["Risk Parity", "Portfolio"],
            "entities": [{"name": "Ray Dalio", "type": "person"}],
        })
        comment = f'<!-- llmwikify:analysis {{"version":1,"hash":"abc","analyzed_at":"2026-01-01","data":{analysis_json}}} -->'
        page.write_text(f"# Analyzed Source\n\n## Summary\nA detailed analysis.\n\n{comment}")

        wiki._update_index_file()
        content = wiki.index_file.read_text()

        assert "Topics: Risk Parity, Portfolio" in content
        assert "Entities: Ray Dalio" in content


class TestLintFixIndexUpdate:
    """Test that lint mode=fix updates the index."""

    def test_lint_fix_updates_index(self, test_wiki):
        """Running lint with mode=fix should update index.md."""
        wiki, tmp = test_wiki
        (wiki.wiki_dir / "concepts" / "Test.md").parent.mkdir(parents=True, exist_ok=True)
        (wiki.wiki_dir / "concepts" / "Test.md").write_text("# Test\n\nA concept page.")

        # Reset index to old format
        wiki.index_file.write_text("# Wiki Index\n\n## Pages\n\n*(No pages yet)*\n")

        result = wiki.lint(mode="fix")

        assert result.get("auto_fix", {}).get("index_updated") is True
        content = wiki.index_file.read_text()
        assert "## Concepts (1)" in content
        assert "A concept page" in content

    def test_lint_check_does_not_update_index(self, test_wiki):
        """Running lint with mode=check should NOT update index.md."""
        wiki, tmp = test_wiki
        original = "# Wiki Index\n\nOld content."
        wiki.index_file.write_text(original)

        wiki.lint(mode="check")

        content = wiki.index_file.read_text()
        assert content == original
