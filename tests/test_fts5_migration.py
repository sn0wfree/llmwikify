"""FTS5 tokenizer auto-migration tests (v0.40.1+).

Verifies that a legacy ``porter unicode61`` pages_fts schema is detected
on first connection and rebuilt with the CJK-friendly tokenizer, with
existing pages' content refilled from the file_path stored in the pages
metadata table.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel.storage.index import _FTS5_TOKENIZE, WikiIndex


class TestFTS5Migration:
    """Auto-migration from legacy to CJK-friendly tokenizer."""

    def _create_legacy_schema(self, db_path: Path) -> None:
        """Create a legacy porter unicode61 FTS5 table and seed one page.

        Mimics a v0.40.0 or earlier wiki index that hasn't yet been touched
        by the new initialize() code path.
        """
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript("""
                CREATE VIRTUAL TABLE pages_fts USING fts5(
                    page_name, content,
                    tokenize='porter unicode61'
                );
                CREATE TABLE page_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_page TEXT NOT NULL,
                    target_page TEXT NOT NULL,
                    section TEXT,
                    display_text TEXT,
                    file_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE pages (
                    page_name TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    content_length INTEGER,
                    word_count INTEGER,
                    link_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        finally:
            conn.close()

    def test_legacy_schema_detected_and_migrated(self, temp_wiki):
        """Connecting to a legacy DB rebuilds pages_fts with new tokenizer."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        # Seed an actual .md file so migration can refill from disk.
        md_file = temp_wiki / "legacy-page.md"
        md_file.write_text(
            "# 配置策略\n\n资产配置原则介绍。",
            encoding="utf-8",
        )

        # Pre-create the legacy schema
        self._create_legacy_schema(db_path)

        # Add a metadata row pointing at the .md file (mimics old index state)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO pages (page_name, file_path, content_length, "
                "word_count, link_count) VALUES (?, ?, ?, ?, ?)",
                ("legacy-page", "legacy-page.md", 100, 20, 0),
            )
            conn.commit()
        finally:
            conn.close()

        # Sanity check: legacy schema is in place
        schema_sql = sqlite3.connect(str(db_path)).execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='pages_fts'"
        ).fetchone()[0]
        assert "porter" in schema_sql
        assert "categories" not in schema_sql

        # Now run WikiIndex.initialize() — should trigger migration
        index = WikiIndex(db_path)
        index.initialize()

        # After migration: schema should reference the new tokenizer + content_seg
        new_schema = index._get_fts_schema_sql()
        assert new_schema is not None
        assert "porter" not in new_schema
        assert "categories" in new_schema
        assert "tokenchars" in new_schema
        assert "content_seg" in new_schema

        # Content should be refilled from the .md file
        results = index.search("配置", limit=10)
        assert any(r["page_name"] == "legacy-page" for r in results)

        index.close()

    def test_legacy_schema_refills_from_wiki_subdir(self, temp_wiki):
        """Migration looks under wiki/ and raw/ subdirs (not just db parent)."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        # Place .md under wiki/ subdir (matches the production layout
        # where db is at root but content lives under root/wiki/).
        wiki_subdir = temp_wiki / "wiki"
        wiki_subdir.mkdir(exist_ok=True)
        md_file = wiki_subdir / "subdir-page.md"
        md_file.write_text(
            "# 算法\n\n机器学习算法介绍。",
            encoding="utf-8",
        )

        self._create_legacy_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO pages (page_name, file_path, content_length, "
                "word_count, link_count) VALUES (?, ?, ?, ?, ?)",
                ("subdir-page", "subdir-page.md", 100, 20, 0),
            )
            conn.commit()
        finally:
            conn.close()

        index = WikiIndex(db_path)
        index.initialize()

        # Should find the page via the wiki/ subdir fallback
        results = index.search("算法", limit=10)
        assert any(r["page_name"] == "subdir-page" for r in results)

        index.close()

    def test_legacy_schema_skips_unfindable_pages(self, temp_wiki):
        """Migration logs skipped count when .md files are missing."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        self._create_legacy_schema(db_path)
        conn = sqlite3.connect(str(db_path))
        try:
            # Point at a non-existent file
            conn.execute(
                "INSERT INTO pages (page_name, file_path, content_length, "
                "word_count, link_count) VALUES (?, ?, ?, ?, ?)",
                ("ghost", "ghost.md", 0, 0, 0),
            )
            conn.commit()
        finally:
            conn.close()

        index = WikiIndex(db_path)
        # Should not raise; migration logs and skips
        index.initialize()

        # Schema migrated
        schema = index._get_fts_schema_sql()
        assert "categories" in schema

        index.close()

    def test_new_schema_no_migration(self, temp_wiki):
        """Connecting to an already-new DB skips migration silently."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        # Schema should have the new tokenizer from the start
        schema = index._get_fts_schema_sql()
        assert "categories" in schema
        assert "porter" not in schema

        # Insert data
        index.upsert_page("a", "# Hello\n\nWorld.", "a.md")

        # Reinitialize (simulate second connection) — should not wipe data
        index.close()
        index2 = WikiIndex(db_path)
        index2.initialize()
        results = index2.search("hello", limit=10)
        assert any(r["page_name"] == "a" for r in results)

        index2.close()

    def test_needs_migration_helper(self, temp_wiki):
        """_needs_migration correctly classifies schemas."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        legacy_sql = (
            "CREATE VIRTUAL TABLE pages_fts USING fts5("
            "page_name, content, tokenize='porter unicode61')"
        )
        new_sql = (
            "CREATE VIRTUAL TABLE pages_fts USING fts5("
            f"page_name, content, content_seg, tokenize=\"{_FTS5_TOKENIZE}\")"
        )
        bare_sql = (
            "CREATE VIRTUAL TABLE pages_fts USING fts5("
            "page_name, content, tokenize='unicode61')"
        )

        assert index._needs_migration(legacy_sql) is True  # no categories, no content_seg
        assert index._needs_migration(new_sql) is False     # has both
        assert index._needs_migration(bare_sql) is True     # no content_seg

        index.close()

    def test_migration_idempotent(self, temp_wiki):
        """Running initialize() twice does not lose data."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        md_file = temp_wiki / "page-a.md"
        md_file.write_text("# Page A\n\n配置方法。", encoding="utf-8")

        index = WikiIndex(db_path)
        index.initialize()
        index.upsert_page("page-a", "# Page A\n\n配置方法。", "page-a.md")
        first_count = index.get_page_count()
        index.close()

        # Re-open — migration logic should be a no-op
        index2 = WikiIndex(db_path)
        index2.initialize()
        second_count = index2.get_page_count()
        assert second_count == first_count
        assert second_count == 1

        index2.close()
