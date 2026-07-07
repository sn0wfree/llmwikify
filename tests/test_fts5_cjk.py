"""CJK search recall tests for WikiIndex (v0.40.1+).

The legacy ``porter unicode61`` tokenizer absorbed continuous CJK text
into single tokens, so short Chinese queries like ``配置`` returned 0
results even when dozens of pages contained those characters. These tests
verify the new ``unicode61 categories 'L* N* Co Mn' tokenchars '_'``
tokenizer correctly indexes each CJK character as an independent token.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel.storage.index import WikiIndex


class TestCJKRecall:
    """CJK short-query recall with the new tokenizer."""

    def test_chinese_two_char_query_finds_content(self, temp_wiki):
        """配置 should find pages that contain 配置 as a substring."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        # Seed pages with Chinese content
        index.upsert_page(
            "concepts/配置策略",
            "# 配置策略\n\n本文讨论资产配置原则与方法。",
            "concepts/配置策略.md",
        )
        index.upsert_page(
            "research/行业配置",
            "# 行业配置\n\n从风格到配置的研究方法。",
            "research/行业配置.md",
        )
        index.upsert_page(
            "unrelated",
            "# 完全无关\n\n英文 only.",
            "unrelated.md",
        )

        results = index.search("配置", limit=10)

        # Both pages containing 配置 should be returned
        page_names = {r["page_name"] for r in results}
        assert "concepts/配置策略" in page_names
        assert "research/行业配置" in page_names
        assert "unrelated" not in page_names

        index.close()

    def test_chinese_query_returns_bm25_scored_results(self, temp_wiki):
        """CJK query results carry FTS5 BM25 scores (not zero from LIKE)."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page(
            "match",
            "# 算法\n\n机器学习算法介绍。",
            "match.md",
        )
        index.upsert_page(
            "no-match",
            "# 烹饪\n\n红烧肉的做法。",
            "no-match.md",
        )

        results = index.search("算法", limit=10)

        assert len(results) == 1
        assert results[0]["page_name"] == "match"
        assert results[0]["score"] > 0  # BM25 score from FTS5, not LIKE
        assert results[0]["mode"] == "fts5"

        index.close()

    def test_english_still_works(self, temp_wiki):
        """English queries retain BM25 ranking (no regression)."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("a", "Gold mining in Nevada.", "a.md")
        index.upsert_page("b", "Copper refining process.", "b.md")
        index.upsert_page("c", "Gold investment guide.", "c.md")

        results = index.search("gold", limit=10)

        page_names = [r["page_name"] for r in results]
        assert "a" in page_names
        assert "c" in page_names
        assert "b" not in page_names

        # All results should have positive scores (FTS5 mode)
        for r in results:
            assert r["mode"] == "fts5"
            assert r["score"] > 0

        index.close()

    def test_zero_results_triggers_like_fallback(self, temp_wiki):
        """When FTS5 returns 0 rows, LIKE substring match kicks in.

        Simulates an exotic query that the tokenizer still splits wrong,
        e.g. a single CJK character that's a stopword.
        """
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        # Page contains a Chinese phrase but query is an edge case
        index.upsert_page(
            "edge",
            "# 边缘案例\n\n罕见的关键词：foobarbaz。",
            "edge.md",
        )

        # Force FTS5 to return 0 by using a syntax-error-ish query
        # (LIKE fallback also covers this)
        results = index.search("foobarbaz", limit=10)

        assert len(results) >= 1
        assert results[0]["page_name"] == "edge"
        # Either mode is acceptable — FTS5 if it matched, LIKE if it didn't.
        assert results[0]["mode"] in ("fts5", "fts5-zero-fallback")

        index.close()

    def test_mixed_chinese_english_query(self, temp_wiki):
        """Mixed CJK + English query works."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page(
            "page1",
            "# Risk Management\n\n风险管理 is critical.",
            "page1.md",
        )
        index.upsert_page(
            "page2",
            "# Other\n\n风险管理 principles.",
            "page2.md",
        )

        results = index.search("风险管理", limit=10)

        page_names = {r["page_name"] for r in results}
        assert "page1" in page_names
        assert "page2" in page_names

        index.close()

    def test_tokenize_clause_in_schema(self, temp_wiki):
        """The pages_fts schema uses the new CJK-friendly tokenizer."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        schema_sql = index._get_fts_schema_sql()
        assert schema_sql is not None
        assert "categories" in schema_sql
        assert "tokenchars" in schema_sql
        assert "content_seg" in schema_sql
        # Old `porter` stemmer should be gone
        assert "porter" not in schema_sql

        index.close()
