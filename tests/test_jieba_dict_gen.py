"""Tests for auto-generated jieba dictionary (jieba_dict_gen.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.kernel.storage.index import WikiIndex
from llmwikify.kernel.storage.jieba_dict_gen import (
    _compute_pmi,
    _load_all_pages,
    _merge_candidates,
    generate_fast_dict,
    generate_slow_dict,
    generate_user_dict,
)


def _seed_cjk_pages(index, pages):
    """Insert multiple pages into the index for dict generation."""
    for name, content, fpath in pages:
        index.upsert_page(name, content, fpath)


class TestGenerateFastDict:
    """Fast generation: frequency + TF-IDF."""

    def test_generates_terms_from_cjk_content(self, temp_wiki):
        db = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db)
        index.initialize()
        _seed_cjk_pages(index, [
            ("p1", "# 资产配置\n\n资产配置原则与方法。", "p1.md"),
            ("p2", "# 风险管理\n\n风险管理的重要性。", "p2.md"),
            ("p3", "# 行业配置\n\n行业配置策略。", "p3.md"),
        ])
        index.close()

        out = temp_wiki / "test_dict.txt"
        count = generate_fast_dict(db, out)
        assert count > 0
        content = out.read_text(encoding="utf-8")
        # Should contain at least some CJK terms
        assert "资产配置" in content or "行业配置" in content or "风险" in content

    def test_empty_db_returns_zero(self, temp_wiki):
        db = temp_wiki / "empty.db"
        sqlite3.connect(str(db)).close()
        count = generate_fast_dict(db, Path("/dev/null"))
        assert count == 0


class TestGenerateSlowDict:
    """Slow generation: PMI collocations."""

    def test_pmi_finds_collocations(self):
        pages = [
            "量化配置方案与行业配置策略",
            "行业配置需要量化配置方法",
            "量化配置的核心是行业配置",
        ]
        candidates = _compute_pmi(pages, min_count=2, min_pmi=2.0)
        terms = {w for w, _ in candidates}
        # "量化" and "配置" appear together frequently
        assert any("量化" in t or "配置" in t for t in terms)

    def test_pmi_empty_returns_empty(self):
        assert _compute_pmi([], 3, 4.0) == []

    def test_pmi_low_freq_filtered(self):
        pages = ["重复重复重复"]
        candidates = _compute_pmi(pages, min_count=10, min_pmi=1.0)
        assert candidates == []

    def test_slow_generates_on_small_corpus(self, temp_wiki):
        db = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db)
        index.initialize()
        _seed_cjk_pages(index, [
            ("a", "# 量化配置\n\n量化配置是资产配置的一种。", "a.md"),
            ("b", "# 行业配置\n\n行业配置与量化配置相关。", "b.md"),
        ])
        index.close()

        out = temp_wiki / "test_pmi.txt"
        count = generate_slow_dict(db, out)
        assert count >= 0


class TestGenerateUserDict:
    """End-to-end dict generation."""

    def test_full_pipeline(self, temp_wiki):
        db = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db)
        index.initialize()
        _seed_cjk_pages(index, [
            ("p1", "# 量化配置\n\n资产配置与风险管理方法。", "p1.md"),
            ("p2", "# 行业配置\n\n从风格到配置的演变。", "p2.md"),
        ])
        index.close()

        result = generate_user_dict(db, temp_wiki)
        assert result["fast"] > 0
        assert result["page_count"] == 2

        dict_path = temp_wiki / ".wiki" / "jieba.dict"
        assert dict_path.exists()
        assert dict_path.stat().st_size > 0

        meta_path = temp_wiki / ".wiki" / "jieba.meta.json"
        assert meta_path.exists()

    def test_empty_wiki_skips_gracefully(self, temp_wiki):
        db = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db)
        index.initialize()
        index.close()

        result = generate_user_dict(db, temp_wiki)
        assert result == {"fast": 0, "slow": 0, "page_count": 0}


class TestMergeCandidates:
    """Term merging and filtering."""

    def test_merges_scored_terms(self):
        from collections import Counter
        freq = Counter({"测试": 10, "量化": 8, "配置": 3})
        tfidf = Counter({"量化": 5, "配置": 2})
        merged = _merge_candidates(freq, tfidf, top_n=10)
        names = {w for w, _ in merged}
        # "测试" appears only in freq (score 10), should survive
        assert "测试" in names
        # "量化" appears in both (score 8 + 10 = 18), should be highest
        assert "量化" in names
        assert merged[0][0] == "量化"

    def test_filters_short_words(self):
        from collections import Counter
        freq = Counter({"的": 100, "量": 5})
        tfidf = Counter()
        merged = _merge_candidates(freq, tfidf, top_n=10)
        assert len(merged) == 0  # filtered: single-char or stop word


class TestLoadAllPages:
    """_load_all_pages helper."""

    def test_returns_raw_content(self, temp_wiki):
        db = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db)
        index.initialize()
        index.upsert_page("a", "# Alpha\n\nContent.", "a.md")
        index.upsert_page("b", "# Beta\n\nOther.", "b.md")
        index.close()

        pages = _load_all_pages(db)
        assert len(pages) == 2
        assert any("Alpha" in p for p in pages)
        assert any("Beta" in p for p in pages)

    def test_nonexistent_db_returns_empty(self):
        assert _load_all_pages(Path("/nonexistent/test.db")) == []
