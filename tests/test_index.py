"""Tests for WikiIndex class - FTS5 search and reference tracking."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import WikiIndex


class TestWikiIndex:
    """Test WikiIndex class."""

    def test_initialize(self, temp_wiki):
        """Test database initialization."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        # Check tables exist
        cursor = index.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        assert 'pages_fts' in tables
        assert 'page_links' in tables
        assert 'pages' in tables

        index.close()

    def test_upsert_page(self, temp_wiki):
        """Test page insertion."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        content = "# Test\n\nContent with [[Another Page]]."
        index.upsert_page("test-page", content, "test.md")

        # Check FTS5
        cursor = index.conn.execute(
            "SELECT COUNT(*) FROM pages_fts WHERE page_name = ?",
            ("test-page",)
        )
        assert cursor.fetchone()[0] == 1

        # Check links
        cursor = index.conn.execute(
            "SELECT COUNT(*) FROM page_links WHERE source_page = ?",
            ("test-page",)
        )
        assert cursor.fetchone()[0] == 1

        index.close()

    def test_search(self, temp_wiki):
        """Test full-text search."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("gold-page", "# Gold\n\nGold mining content", "gold.md")
        index.upsert_page("copper-page", "# Copper\n\nCopper mining content", "copper.md")

        results = index.search("gold", limit=10)

        assert len(results) == 1
        assert results[0]['page_name'] == 'gold-page'

        index.close()

    def test_get_inbound_links(self, temp_wiki):
        """Test inbound links query."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        # Create links: A -> B, C -> B
        index.upsert_page("page-a", "# A\n\n[[page-b]]", "a.md")
        index.upsert_page("page-c", "# C\n\n[[page-b]]", "c.md")
        index.upsert_page("page-b", "# B", "b.md")

        inbound = index.get_inbound_links("page-b")

        assert len(inbound) == 2
        sources = [i['source'] for i in inbound]
        assert 'page-a' in sources
        assert 'page-c' in sources

        index.close()

    def test_get_outbound_links(self, temp_wiki):
        """Test outbound links query."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        content = "# A\n\nLinks to [[page-b]] and [[page-c#section|Custom]]."
        index.upsert_page("page-a", content, "a.md")

        outbound = index.get_outbound_links("page-a")

        assert len(outbound) == 2
        targets = [o['target'] for o in outbound]
        assert 'page-b' in targets
        assert 'page-c' in targets

        index.close()

    def test_export_json(self, temp_wiki):
        """Test JSON export."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("page-a", "# A\n\n[[page-b]]", "a.md")
        index.upsert_page("page-b", "# B", "b.md")

        output_path = temp_wiki / "test_export.json"
        data = index.export_json(output_path)

        assert data['total_pages'] == 2
        assert 'page-a' in data['outbound_links']
        assert 'page-b' in data['inbound_links']

        # Verify file created
        assert output_path.exists()

        # Verify structure
        with open(output_path) as f:
            loaded = json.load(f)

        assert loaded['total_pages'] == 2
        assert 'summary' in loaded

        index.close()

    def test_delete_page(self, temp_wiki):
        """Test page deletion."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("test", "# Test", "test.md")
        assert index.get_page_count() == 1

        index.delete_page("test")
        assert index.get_page_count() == 0

        index.close()

    def test_parse_links(self, temp_wiki):
        """Test link parsing."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)

        content = """
        # Test
        
        Simple: [[page-a]]
        Custom: [[page-b|Display]]
        Section: [[page-c#section]]
        Full: [[page-d#section|Custom]]
        """

        links = index._parse_links(content, "test.md")

        assert len(links) == 4

        assert links[0]['target'] == 'page-a'
        assert links[0]['section'] == ''
        assert links[0]['display'] == 'page-a'

        assert links[1]['target'] == 'page-b'
        assert links[1]['display'] == 'Display'

        assert links[2]['target'] == 'page-c'
        assert links[2]['section'] == '#section'

        assert links[3]['target'] == 'page-d'
        assert links[3]['section'] == '#section'
        assert links[3]['display'] == 'Custom'

        index.close()
