"""Tests for direct lint (schema-aware gap detection)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core import Wiki


class TestBuildLintContext:
    """Test _build_lint_context method."""

    def test_context_includes_wiki_md(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        context = wiki._build_lint_context()

        assert "=== WIKI SCHEMA (wiki.md) ===" in context
        assert "Page Types" in context

        wiki.close()

    def test_context_includes_page_list(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Test Entity", "# Test Entity\n", page_type="Entity")
        wiki.write_page("Test Concept", "# Test Concept\n", page_type="Concept")

        context = wiki._build_lint_context()

        assert "=== EXISTING PAGES" in context
        assert "Test Entity" in context
        assert "Test Concept" in context

        wiki.close()

    def test_context_includes_source_files(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / "raw" / "test1.md").write_text("# Source 1\n")
        (temp_wiki / "raw" / "test2.md").write_text("# Source 2\n")

        context = wiki._build_lint_context()

        assert "=== SOURCE ANALYSIS" in context
        assert "test1.md" in context
        assert "test2.md" in context

        wiki.close()

    def test_context_limits_source_files(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        for i in range(25):
            (temp_wiki / "raw" / f"source_{i}.md").write_text(f"# Source {i}\n")

        context = wiki._build_lint_context(limit=20)

        assert "=== SOURCE ANALYSIS" in context
        assert "and 5 more" in context

        wiki.close()

    def test_context_limits_source_files(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        for i in range(25):
            (temp_wiki / "raw" / f"source_{i}.md").write_text(f"# Source {i}\n")

        context = wiki._build_lint_context(limit=20)

        assert "=== SOURCE ANALYSIS" in context
        assert "and 5 more" in context

        wiki.close()

    def test_context_handles_empty_wiki(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        context = wiki._build_lint_context()

        assert "=== EXISTING PAGES" in context

        wiki.close()


class TestFallbackDetectGaps:
    """Test _fallback_detect_gaps method."""

    def test_fallback_returns_list(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        gaps = wiki._fallback_detect_gaps()

        assert isinstance(gaps, list)

        wiki.close()

    def test_fallback_detects_orphan_concepts(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        engine = wiki.get_relation_engine()
        engine.add_relation("OrphanConcept", "KnownEntity", "related_to", "EXTRACTED")

        gaps = wiki._fallback_detect_gaps()

        orphan_types = [g["type"] for g in gaps]
        assert "orphan_concept" in orphan_types

        wiki.close()


class TestLintSignature:
    """Test lint() method new signature."""

    def test_lint_default_params(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint()

        assert "issues" in result
        assert "issue_count" in result
        assert "mode" in result
        assert result["mode"] == "check"
        assert "schema_source" in result

        wiki.close()

    def test_lint_mode_parameter(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint(mode="fix")

        assert result["mode"] == "fix"

        wiki.close()

    def test_lint_limit_parameter(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint(limit=5)

        llm_gaps = [i for i in result["issues"] if "type" in i and i["type"] in (
            "missing_custom_page", "orphan_concept", "missing_cross_ref",
            "non_compliant_page", "broken_link"
        )]
        assert len(llm_gaps) <= 5

        wiki.close()

    def test_lint_returns_schema_source(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint()

        assert result["schema_source"] == "wiki.md (direct)"

        wiki.close()

    def test_lint_backward_compat(self, temp_wiki):
        """Test that old signature still works."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint(generate_investigations=False)

        assert "issues" in result
        assert "hints" in result
        assert "investigations" in result

        wiki.close()


class TestLLMDetectGaps:
    """Test _llm_detect_gaps method."""

    def test_llm_fallback_on_no_client(self, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        gaps = wiki._llm_detect_gaps("test context")

        assert isinstance(gaps, list)

        wiki.close()

    @patch('llmwikify.llm_client.LLMClient')
    def test_llm_parses_list_response(self, mock_client_class, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        mock_client = MagicMock()
        mock_client.chat_json.return_value = [
            {"type": "orphan_concept", "concept": "TestConcept"},
        ]
        mock_client_class.from_config.return_value = mock_client

        gaps = wiki._llm_detect_gaps("test context")

        assert len(gaps) == 1
        assert gaps[0]["type"] == "orphan_concept"

        wiki.close()

    @patch('llmwikify.llm_client.LLMClient')
    def test_llm_parses_dict_with_gaps(self, mock_client_class, temp_wiki):
        wiki = Wiki(temp_wiki)
        wiki.init()

        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "gaps": [
                {"type": "missing_custom_page", "page_name": "Test"},
            ]
        }
        mock_client_class.from_config.return_value = mock_client

        gaps = wiki._llm_detect_gaps("test context")

        assert len(gaps) == 1
        assert gaps[0]["type"] == "missing_custom_page"

        wiki.close()
