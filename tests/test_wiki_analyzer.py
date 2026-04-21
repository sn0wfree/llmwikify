"""Unit tests for WikiAnalyzer — the standalone health check engine."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core.wiki_analyzer import WikiAnalyzer


@pytest.fixture
def mock_wiki(tmp_path):
    """Create a minimal mock Wiki instance."""
    wiki = MagicMock()
    wiki.root = tmp_path
    wiki.wiki_dir = tmp_path / "wiki"
    wiki.wiki_dir.mkdir(exist_ok=True)
    wiki.raw_dir = tmp_path / "raw"
    wiki.raw_dir.mkdir(exist_ok=True)
    wiki.wiki_md_file = tmp_path / "wiki.md"
    wiki.wiki_md_file.write_text("# Wiki Schema\n")
    wiki.index = MagicMock()
    wiki.index.get_inbound_links.return_value = []
    wiki.query_sink = MagicMock()
    wiki.query_sink.status.return_value = {"sinks": []}
    wiki._wiki_pages.return_value = []
    wiki._page_display_name.side_effect = lambda p: p.stem
    wiki._index_page_name = "Index"
    wiki._log_page_name = "Log"
    wiki._should_exclude_orphan.return_value = False
    wiki._resolve_wikilink_target.return_value = None
    wiki._get_existing_page_names.return_value = []
    wiki._find_source_summary_page.return_value = None
    wiki._get_cached_source_analysis.return_value = None
    wiki.get_relation_engine.side_effect = Exception("No relation engine")
    wiki.config = {}
    wiki._get_prompt_registry.side_effect = Exception("No prompt registry")
    wiki.fix_wikilinks.return_value = {"fixed": 0, "skipped": 0, "ambiguous": 0, "changes": []}
    wiki._update_index_file.return_value = None
    return wiki


class TestWikiAnalyzerInit:
    """Test WikiAnalyzer initialization."""

    def test_init_stores_wiki(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        assert analyzer.wiki is mock_wiki


class TestDetectDatedClaims:
    """Test _detect_dated_claims."""

    def test_empty_when_no_raw_sources(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_dated_claims()
        assert result == []

    def test_detects_outdated_claim(self, mock_wiki, tmp_path):
        # Create a raw source with recent year
        raw_file = mock_wiki.raw_dir / "recent.txt"
        raw_file.write_text("Data from 2024")

        # Create a wiki page with old year
        old_page = mock_wiki.wiki_dir / "old_topic.md"
        old_page.write_text("# Old Topic\nThis was true in 2019.\n")

        mock_wiki._wiki_pages.return_value = [old_page]

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_dated_claims()

        assert len(result) == 1
        assert result[0]["type"] == "dated_claim"
        assert result[0]["claim_year"] == 2019
        assert result[0]["latest_source_year"] == 2024


class TestDetectMissingCrossRefs:
    """Test _detect_missing_cross_refs."""

    def test_empty_when_no_pages(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_missing_cross_refs()
        assert result == []

    def test_detects_unlinked_mentions(self, mock_wiki):
        page_a = mock_wiki.wiki_dir / "TopicA.md"
        page_a.write_text("# Topic A\nThis relates to TopicB heavily.\n")
        page_b = mock_wiki.wiki_dir / "TopicB.md"
        page_b.write_text("# Topic B\nAlso related to TopicA.\n")
        page_c = mock_wiki.wiki_dir / "TopicC.md"
        page_c.write_text("# Topic C\nTopicA is important here too.\n")

        mock_wiki._wiki_pages.return_value = [page_a, page_b, page_c]

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_missing_cross_refs()

        assert len(result) >= 1
        assert result[0]["type"] == "missing_cross_ref"


class TestDetectRedundancy:
    """Test _detect_redundancy."""

    def test_empty_when_no_pages(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_redundancy()
        assert result == []

    def test_detects_similar_names(self, mock_wiki):
        page_a = mock_wiki.wiki_dir / "Machine Learning.md"
        page_a.write_text("# Machine Learning\n")
        page_b = mock_wiki.wiki_dir / "Machine Learning Basics.md"
        page_b.write_text("# ML Basics\n")

        mock_wiki._wiki_pages.return_value = [page_a, page_b]

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._detect_redundancy()

        assert len(result) == 1
        assert result[0]["type"] == "similar_page_names"


class TestRecommend:
    """Test recommend."""

    def test_empty_when_no_pages(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.recommend()
        assert result["missing_pages"] == []
        assert result["orphan_pages"] == []

    def test_finds_missing_pages(self, mock_wiki):
        page_a = mock_wiki.wiki_dir / "Main.md"
        page_a.write_text("# Main\nSee [[MissingPage]] and [[MissingPage]] again.\n")

        mock_wiki._wiki_pages.return_value = [page_a]
        mock_wiki._resolve_wikilink_target.return_value = None

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.recommend()

        assert len(result["missing_pages"]) >= 1
        assert result["missing_pages"][0]["page"] == "MissingPage"


class TestLint:
    """Test lint orchestration."""

    def test_returns_structure(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.lint()

        assert "total_pages" in result
        assert "issue_count" in result
        assert "issues" in result
        assert "mode" in result
        assert "hints" in result
        assert "investigations" in result
        assert "sink_status" in result

    def test_detects_broken_links(self, mock_wiki):
        page = mock_wiki.wiki_dir / "Test.md"
        page.write_text("# Test\nSee [[BrokenLink]].\n")

        mock_wiki._wiki_pages.return_value = [page]
        mock_wiki._resolve_wikilink_target.return_value = None
        mock_wiki.index.get_inbound_links.return_value = ["some_link"]

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.lint()

        broken = [i for i in result["issues"] if i["type"] == "broken_link"]
        assert len(broken) == 1

    def test_detects_orphan_pages(self, mock_wiki):
        page = mock_wiki.wiki_dir / "Orphan.md"
        page.write_text("# Orphan\n")

        mock_wiki._wiki_pages.return_value = [page]
        mock_wiki.index.get_inbound_links.return_value = []

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.lint()

        orphans = [i for i in result["issues"] if i["type"] == "orphan_page"]
        assert len(orphans) == 1

    def test_fix_mode_calls_fix_wikilinks(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer.lint(mode="fix")

        assert "auto_fix" in result
        mock_wiki.fix_wikilinks.assert_called_once_with(dry_run=False)


class TestGenerateHints:
    """Test _generate_hints."""

    def test_empty_when_no_issues(self, mock_wiki):
        mock_wiki.index.get_inbound_links.return_value = ["link"]
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._generate_hints()

        assert "hints" in result
        assert "summary" in result

    def test_reports_orphan_pages(self, mock_wiki):
        page = mock_wiki.wiki_dir / "Orphan.md"
        page.write_text("# Orphan\n")
        mock_wiki._wiki_pages.return_value = [page]
        mock_wiki.index.get_inbound_links.return_value = []

        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._generate_hints()

        orphan_hints = [h for h in result["hints"] if h["type"] == "orphan"]
        assert len(orphan_hints) == 1


class TestFallbackDetectGaps:
    """Test _fallback_detect_gaps."""

    def test_returns_empty_when_no_relation_engine(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._fallback_detect_gaps()
        assert isinstance(result, list)


class TestLLMGenerateInvestigations:
    """Test _llm_generate_investigations."""

    def test_returns_warning_when_no_llm(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        result = analyzer._llm_generate_investigations([], [])

        assert "warning" in result
        assert "suggested_questions" in result
        assert "suggested_sources" in result


class TestBuildLintContext:
    """Test _build_lint_context."""

    def test_includes_wiki_schema(self, mock_wiki):
        analyzer = WikiAnalyzer(mock_wiki)
        context = analyzer._build_lint_context()

        assert "WIKI SCHEMA" in context

    def test_includes_page_list(self, mock_wiki):
        mock_wiki._get_existing_page_names.return_value = ["PageA", "PageB"]
        analyzer = WikiAnalyzer(mock_wiki)
        context = analyzer._build_lint_context()

        assert "EXISTING PAGES" in context
        assert "PageA" in context
