# tests/scenarios/test_01_wiki_core.py
"""Scenario 1: Wiki Core - No LLM required.

## Background
Core wiki operations: initialize a wiki directory, write/read markdown
pages, search via FTS5, build bidirectional link index, run lint.

## Architecture
```mermaid
graph LR
    User[User] -->|create_wiki| Wiki
    User -->|write/read| Wiki
    User -->|search/lint| Wiki
    Wiki -->|reads| MD[wiki/<br/>markdown pages]
    Wiki <-->|FTS5 + ref| DB[(.llmwikify.db)]
```

## Troubleshooting
- Init fails with "already exists": use --overwrite
- Search returns 0: run build_index first
- Lint shows broken links: check [[wikilink]] targets
"""


class TestWikiCore:
    """Test core wiki operations: init, ingest, write, search, lint.

    Covers the 8 core operations in TUTORIAL.md Scenario 1.
    """

    def test_1_1_init_wiki(self, wiki, temp_dir):
        """Step 1.1: Initialize wiki directory structure.

        Creates a Wiki instance with raw/ + wiki/ subdirectories.
        No LLM required.

        ## Expected Output
        ```
        Wiki root: <temp_dir>/test-wiki
        ```
        """
        assert wiki is not None
        assert hasattr(wiki, "root")
        assert hasattr(wiki, "wiki_dir")
        assert hasattr(wiki, "raw_dir")

    def test_1_2_write_page(self, wiki):
        """Step 1.2: Write a markdown page and read it back.

        Uses wiki.write_page() to create a page, then read_page() to
        verify it was stored correctly.
        """
        content = "# Test Page\n\nThis is a test page with some content."
        wiki.write_page("test-page", content)

        result = wiki.read_page("test-page")
        assert isinstance(result, dict)
        assert "Test Page" in result.get("content", "")

    def test_1_3_write_multiple_pages(self, wiki, sample_pages):
        """Step 1.3: Write multiple pages in a loop.

        Demonstrates batch writing pattern for initializing a wiki
        with several pages at once.
        """
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        for name in sample_pages:
            result = wiki.read_page(name)
            assert result is not None
            assert isinstance(result, dict)

    def test_1_4_search(self, wiki, sample_pages):
        """Step 1.4: Full-text search via FTS5.

        Searches for "Python" across all wiki pages using SQLite FTS5.
        """
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        results = wiki.search("Python", limit=10)
        assert len(results) > 0

    def test_1_5_build_index(self, wiki, sample_pages):
        """Step 1.5: Build the bidirectional reference index.

        Scans all wiki/*.md files, parses [[wikilink]] syntax, and
        populates the page_links table for backlink queries.
        """
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        idx = wiki.build_index()
        assert "total_pages" in idx
        assert idx["total_pages"] >= 3

    def test_1_6_bidirectional_links(self, wiki):
        """Step 1.6: Query inbound and outbound links.

        Demonstrates the bidirectional link system: who links TO a page
        (inbound) and what a page links TO (outbound).
        """
        wiki.write_page("page-a", "# Page A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# Page B\n\nLinked from [[page-a]].")
        wiki.build_index()

        inbound = wiki.get_inbound_links("page-b")
        assert len(inbound) > 0

        outbound = wiki.get_outbound_links("page-a")
        assert len(outbound) > 0

    def test_1_7_lint(self, wiki, sample_pages):
        """Step 1.7: Run health check via lint().

        Returns issues (broken links, orphans) and hints (improvement
        suggestions) for the wiki.
        """
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        result = wiki.lint()
        assert "issues" in result
        assert "hints" in result

    def test_1_8_status(self, wiki, sample_pages):
        """Step 1.8: Get wiki statistics.

        Returns total page count, link count, and other health metrics.
        """
        for name, content in sample_pages.items():
            wiki.write_page(name, content)

        status = wiki.status()
        assert "page_count" in status or "total_pages" in status
