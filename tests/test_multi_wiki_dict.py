"""Multi-wiki dictionary independence tests.

Each wiki has its own ``.wiki/jieba.dict`` generated from its own content.
When both are loaded into jieba (global singleton), terms accumulate
without conflict.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.kernel.storage.index import WikiIndex


class TestMultiWikiDict:
    """Verify each wiki generates its own independent dict."""

    def _seed_wiki(self, root, pages):
        """Create a minimal wiki with given pages."""
        (root / "wiki").mkdir(parents=True, exist_ok=True)
        (root / "raw").mkdir(parents=True, exist_ok=True)
        db = root / ".llmwikify.db"
        index = WikiIndex(db)
        index.initialize()
        for name, content, fpath in pages:
            index.upsert_page(name, content, fpath)
        index.close()
        return db

    def test_independent_dicts_per_wiki(self, temp_wiki):
        """Two wikis generate different dicts based on their content."""
        wiki_a = temp_wiki / "wiki-a"
        wiki_b = temp_wiki / "wiki-b"
        wiki_a.mkdir()
        wiki_b.mkdir()

        self._seed_wiki(wiki_a, [
            ("p1", "# 量化配置\n\n资产配置方法。", "p1.md"),
        ])
        self._seed_wiki(wiki_b, [
            ("p1", "# 机器学习\n\n深度学习算法。", "p1.md"),
        ])

        # Generate dicts
        from llmwikify.kernel.storage.jieba_dict_gen import generate_user_dict
        result_a = generate_user_dict(wiki_a / ".llmwikify.db", wiki_a)
        result_b = generate_user_dict(wiki_b / ".llmwikify.db", wiki_b)

        assert result_a["page_count"] == 1
        assert result_b["page_count"] == 1

        dict_a = wiki_a / ".wiki" / "jieba.dict"
        dict_b = wiki_b / ".wiki" / "jieba.dict"
        assert dict_a.exists()
        assert dict_b.exists()

        # Content of dicts should differ (different domain vocab)
        words_a = {line.split("\t")[0] for line in dict_a.read_text().splitlines() if line.strip()}
        words_b = {line.split("\t")[0] for line in dict_b.read_text().splitlines() if line.strip()}
        assert words_a != words_b, "Different wikis should generate different dicts"
        # Each should contain domain-relevant terms
        assert any("配置" in w for w in words_a) or any("量化" in w for w in words_a)
        assert any("机器" in w or "学习" in w or "算法" in w for w in words_b)

    def test_dict_loading_does_not_conflict(self, temp_wiki):
        """Loading two wiki dicts into jieba accumulates without error."""
        wiki_a = temp_wiki / "wiki-a"
        wiki_b = temp_wiki / "wiki-b"
        wiki_a.mkdir()
        wiki_b.mkdir()

        self._seed_wiki(wiki_a, [
            ("p1", "# Alpha\n\nContent A.", "p1.md"),
        ])
        self._seed_wiki(wiki_b, [
            ("p1", "# Beta\n\nContent B.", "p1.md"),
        ])

        from llmwikify.kernel.storage.jieba_dict_gen import generate_user_dict
        generate_user_dict(wiki_a / ".llmwikify.db", wiki_a)
        generate_user_dict(wiki_b / ".llmwikify.db", wiki_b)

        # Opening both WikiIndexes should not raise
        idx_a = WikiIndex(wiki_a / ".llmwikify.db")
        idx_b = WikiIndex(wiki_b / ".llmwikify.db")
        idx_a.initialize()
        idx_b.initialize()

        assert idx_a._ensure_dict is not None
        assert idx_b._ensure_dict is not None

        idx_a.close()
        idx_b.close()
