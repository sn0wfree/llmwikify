"""Tests for source analysis caching."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core import Wiki


class TestComputeContentHash:
    """Test _compute_content_hash method."""

    def test_hash_consistent(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "raw" / "test.md").write_text("Hello world")

        hash1 = wiki._compute_content_hash("raw/test.md")
        hash2 = wiki._compute_content_hash("raw/test.md")

        assert hash1 == hash2

        wiki.close()

    def test_hash_differs_on_content_change(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "raw" / "test.md").write_text("Hello world")
        hash1 = wiki._compute_content_hash("raw/test.md")

        (temp_wiki / "raw" / "test.md").write_text("Hello universe")
        hash2 = wiki._compute_content_hash("raw/test.md")

        assert hash1 != hash2

        wiki.close()


class TestFindSourceSummaryPage:
    """Test _find_source_summary_page method."""

    def test_find_by_slug(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (temp_wiki / "wiki" / "sources" / "nvidia-article.md").write_text("# NVIDIA Article\n")

        result = wiki._find_source_summary_page("raw/nvidia-article.md")

        assert result is not None
        assert result.name == "nvidia-article.md"

        wiki.close()

    def test_returns_none_if_no_page(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki._find_source_summary_page("raw/nonexistent.md")

        assert result is None

        wiki.close()

    def test_returns_none_if_no_sources_dir(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki._find_source_summary_page("raw/test.md")

        assert result is None

        wiki.close()


class TestCacheSourceAnalysis:
    """Test _cache_source_analysis and _get_cached_source_analysis methods."""

    def test_cache_and_retrieve(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        page = temp_wiki / "wiki" / "sources" / "test.md"
        page.write_text("# Test\n")

        analysis = {
            "entities": [{"name": "NVIDIA", "type": "organization"}],
            "topics": ["AI"],
            "suggested_pages": [{"name": "Blackwell", "type": "Model"}],
        }

        wiki._cache_source_analysis(page, "abc123", analysis)
        cached = wiki._get_cached_source_analysis(page)

        assert cached is not None
        assert cached['hash'] == 'abc123'
        assert cached['data']['entities'][0]['name'] == 'NVIDIA'

        wiki.close()

    def test_overwrite_existing_cache(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        page = temp_wiki / "wiki" / "sources" / "test.md"
        page.write_text("# Test\n")

        analysis1 = {"entities": [{"name": "A"}]}
        analysis2 = {"entities": [{"name": "B"}]}

        wiki._cache_source_analysis(page, "hash1", analysis1)
        wiki._cache_source_analysis(page, "hash2", analysis2)

        cached = wiki._get_cached_source_analysis(page)
        assert cached['data']['entities'][0]['name'] == 'B'

        wiki.close()

    def test_returns_none_if_no_cache(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        page = temp_wiki / "wiki" / "sources" / "test.md"
        page.write_text("# Test\n")

        cached = wiki._get_cached_source_analysis(page)

        assert cached is None

        wiki.close()


class TestAnalyzeSource:
    """Test analyze_source method."""

    def test_skip_without_llm(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "raw" / "test.md").write_text("Test content")

        result = wiki.analyze_source("raw/test.md")

        assert result["status"] == "skipped"

        wiki.close()

    @patch('llmwikify.llm_client.LLMClient')
    def test_calls_llm_and_caches(self, mock_client_class, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (temp_wiki / "wiki" / "sources" / "test.md").write_text("# Test\n")
        (temp_wiki / "raw" / "test.md").write_text("Test content about AI and NVIDIA")

        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "entities": [{"name": "NVIDIA", "type": "organization"}],
            "topics": ["AI"],
            "suggested_pages": [{"name": "Blackwell", "type": "Model"}],
        }
        mock_client_class.from_config.return_value = mock_client

        result = wiki.analyze_source("raw/test.md")

        assert result["entities"][0]["name"] == "NVIDIA"

        # Verify cached
        source_page = wiki._find_source_summary_page("raw/test.md")
        cached = wiki._get_cached_source_analysis(source_page)
        assert cached['data']['entities'][0]['name'] == 'NVIDIA'

        wiki.close()

    @patch('llmwikify.llm_client.LLMClient')
    def test_force_reanalysis(self, mock_client_class, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (temp_wiki / "wiki" / "sources" / "test.md").write_text("# Test\n")
        (temp_wiki / "raw" / "test.md").write_text("Test content")

        call_count = 0

        def mock_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"entities": [], "topics": [], "suggested_pages": []}

        mock_client = MagicMock()
        mock_client.chat_json = mock_chat
        mock_client_class.from_config.return_value = mock_client

        # First call
        wiki.analyze_source("raw/test.md")
        assert call_count == 1

        # Second call (should use cache)
        wiki.analyze_source("raw/test.md")
        assert call_count == 1

        # Force call (should call LLM again)
        wiki.analyze_source("raw/test.md", force=True)
        assert call_count == 2

        wiki.close()


class TestBuildLintContext:
    """Test _build_lint_context with source analysis."""

    def test_shows_analyzed_source(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        page = temp_wiki / "wiki" / "sources" / "test.md"
        page.write_text("# Test\n")

        (temp_wiki / "raw" / "test.md").write_text("Test content")

        analysis = {
            "entities": [{"name": "NVIDIA", "type": "organization"}],
            "topics": ["AI"],
            "suggested_pages": [{"name": "Blackwell", "type": "Model"}],
        }
        wiki._cache_source_analysis(page, "abc123", analysis)

        context = wiki._build_lint_context()

        assert "Entities: NVIDIA" in context
        assert "Suggested pages: Blackwell(Model)" in context

        wiki.close()

    def test_shows_not_analyzed_source(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (temp_wiki / "wiki" / "sources" / "test.md").write_text("# Test\n")
        (temp_wiki / "raw" / "test.md").write_text("Test content")

        context = wiki._build_lint_context()

        assert "[NOT ANALYZED]" in context

        wiki.close()

    def test_shows_unanalyzed_hint(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (temp_wiki / "wiki" / "sources" / "test.md").write_text("# Test\n")
        (temp_wiki / "raw" / "test.md").write_text("Test content")

        context = wiki._build_lint_context()

        assert "UNANALYZED SOURCES" in context
        assert "analyze-source --all" in context

        wiki.close()
