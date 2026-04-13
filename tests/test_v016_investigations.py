"""Tests for v0.16.0 — Smart Investigations (contradictions + data gaps + LLM suggestions)."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from llmwikify import Wiki


@pytest.fixture
def temp_wiki():
    """Create a temporary wiki for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = Wiki(Path(tmpdir))
        wiki.init()
        yield wiki


class TestContradictionDetection:
    """Test _detect_potential_contradictions method."""
    
    def test_detects_value_conflicts(self, temp_wiki):
        """Test detection of conflicting values across pages."""
        temp_wiki.write_page("Company A", "# Company A\n\n- Revenue: $10M\n- Status: Active\n")
        temp_wiki.write_page("Company A Financials", "# Company A Financials\n\n- Revenue: $15M\n- Status: Active\n")
        
        result = temp_wiki._detect_potential_contradictions()
        assert len(result) > 0
        assert any(c["type"] == "value_conflict" for c in result)
    
    def test_detects_year_conflicts(self, temp_wiki):
        """Test detection of conflicting year claims."""
        temp_wiki.write_page("Product X", "# Product X\n\nProduct X launched in 2020\n")
        temp_wiki.write_page("History", "# History\n\nProduct X founded in 2022\n")
        
        result = temp_wiki._detect_potential_contradictions()
        assert any(c["type"] == "year_conflict" for c in result)
    
    def test_detects_negation_patterns(self, temp_wiki):
        """Test detection of contradictory negation patterns."""
        temp_wiki.write_page("Status", "# Status\n\nThe company is active in mining.\n")
        temp_wiki.write_page("Update", "# Update\n\nThe company is not active in mining.\n")
        
        result = temp_wiki._detect_potential_contradictions()
        assert any(c["type"] == "negation_pattern" for c in result)
    
    def test_no_contradictions_on_consistent_data(self, temp_wiki):
        """Test no false positives when data is consistent."""
        temp_wiki.write_page("Company A", "# Company A\n\nRevenue: $10M\n")
        temp_wiki.write_page("Other", "# Other\n\nSomething else entirely\n")
        
        result = temp_wiki._detect_potential_contradictions()
        # Should not flag unrelated content
        value_conflicts = [c for c in result if c["type"] == "value_conflict"]
        assert len(value_conflicts) == 0
    
    def test_max_3_contradictions(self, temp_wiki):
        """Test that max 3 contradictions are returned."""
        # Create multiple conflicting pages
        for i in range(10):
            temp_wiki.write_page(f"Page {i}", f"# Page {i}\n\nRevenue: ${i}M\n")
        
        result = temp_wiki._detect_potential_contradictions()
        assert len(result) <= 3
    
    def test_empty_wiki(self, temp_wiki):
        """Test with no wiki pages."""
        result = temp_wiki._detect_potential_contradictions()
        assert result == []


class TestDataGapDetection:
    """Test _detect_data_gaps method."""
    
    def test_detects_unsourced_claims(self, temp_wiki):
        """Test detection of claims without sources."""
        content = (
            "# Market Analysis\n\n"
            "The market grew 50% last year.\n"
            "Company A leads the sector.\n"
            "Revenue exceeded expectations.\n"
            "New competitors emerged.\n"
        )
        temp_wiki.write_page("Market Analysis", content)
        
        result = temp_wiki._detect_data_gaps()
        assert any(g["type"] == "unsourced_claims" for g in result)
    
    def test_detects_vague_temporal(self, temp_wiki):
        """Test detection of vague time references."""
        content = (
            "# Update\n\n"
            "Recently, the company announced changes.\n"
            "Soon, new products will launch.\n"
        )
        temp_wiki.write_page("Update", content)
        
        result = temp_wiki._detect_data_gaps()
        assert any(g["type"] == "vague_temporal" for g in result)
    
    def test_no_gaps_with_sources(self, temp_wiki):
        """Test no false positives when sources are cited."""
        content = (
            "# Market Analysis\n\n"
            "The market grew 50% last year.\n"
            "Company A leads the sector.\n"
            "Revenue exceeded expectations.\n"
            "New competitors emerged.\n\n"
            "## Sources\n"
            "- [Source: Report](raw/report.md)\n"
        )
        temp_wiki.write_page("Market Analysis", content)
        
        result = temp_wiki._detect_data_gaps()
        unsourced = [g for g in result if g["type"] == "unsourced_claims" and g["page"] != "overview"]
        assert len(unsourced) == 0
    
    def test_max_3_gaps(self, temp_wiki):
        """Test that max 3 gaps are returned."""
        for i in range(10):
            content = (
                f"# Page {i}\n\n"
                f"Statement one about topic {i}.\n"
                f"Statement two about topic {i}.\n"
                f"Statement three about topic {i}.\n"
            )
            temp_wiki.write_page(f"Page {i}", content)
        
        result = temp_wiki._detect_data_gaps()
        # overview.md may also have gaps, so check for at most 3 + 1
        assert len(result) <= 4
    
    def test_empty_wiki(self, temp_wiki):
        """Test with no wiki pages (overview.md exists by default)."""
        result = temp_wiki._detect_data_gaps()
        # overview.md has placeholder content with unsourced claims
        # Filter it out to test the "empty" case
        non_overview = [g for g in result if g["page"] != "overview"]
        assert non_overview == []


class TestLLMInvestigations:
    """Test _llm_generate_investigations method."""
    
    @patch('llmwikify.llm_client.LLMClient')
    def test_generates_suggestions(self, mock_client_class, temp_wiki):
        """Test LLM generates investigation suggestions."""
        # Mock LLM client
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "suggested_questions": ["What is the actual revenue?", "When was the product launched?"],
            "suggested_sources": ["Financial reports", "Press releases"],
        }
        mock_client_class.from_config.return_value = mock_client
        
        contradictions = [{"type": "value_conflict", "observation": "Test"}]
        data_gaps = [{"type": "unsourced_claims", "observation": "Test"}]
        
        result = temp_wiki._llm_generate_investigations(contradictions, data_gaps)
        
        assert len(result["suggested_questions"]) > 0
        assert len(result["suggested_sources"]) > 0
        assert "warning" not in result
    
    def test_returns_empty_when_no_llm(self, temp_wiki):
        """Test graceful fallback when LLM not available."""
        contradictions = []
        data_gaps = []
        
        result = temp_wiki._llm_generate_investigations(contradictions, data_gaps)
        
        assert result["suggested_questions"] == []
        assert result["suggested_sources"] == []
        assert "warning" in result


class TestLintInvestigations:
    """Test lint() integration with investigations."""
    
    def test_lint_returns_investigations(self, temp_wiki):
        """Test that lint() includes investigations key."""
        result = temp_wiki.lint()
        
        assert "investigations" in result
        assert "contradictions" in result["investigations"]
        assert "data_gaps" in result["investigations"]
    
    def test_lint_without_llm_suggestions(self, temp_wiki):
        """Test lint() without LLM suggestions (default)."""
        result = temp_wiki.lint(generate_investigations=False)
        
        assert "investigations" in result
        assert "suggested_questions" not in result["investigations"]
        assert "suggested_sources" not in result["investigations"]
    
    @patch('llmwikify.llm_client.LLMClient')
    def test_lint_with_llm_suggestions(self, mock_client_class, temp_wiki):
        """Test lint() with LLM suggestions enabled."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "suggested_questions": ["Question 1"],
            "suggested_sources": ["Source 1"],
        }
        mock_client_class.from_config.return_value = mock_client
        
        result = temp_wiki.lint(generate_investigations=True)
        
        assert "suggested_questions" in result["investigations"]
        assert "suggested_sources" in result["investigations"]
        assert len(result["investigations"]["suggested_questions"]) > 0
    
    def test_lint_preserves_existing_structure(self, temp_wiki):
        """Test that lint() still returns all existing keys."""
        result = temp_wiki.lint()
        
        assert "total_pages" in result
        assert "issue_count" in result
        assert "issues" in result
        assert "hints" in result
        assert "critical" in result["hints"]
        assert "informational" in result["hints"]
        assert "sink_status" in result
        assert "sink_warnings" in result
        assert "investigations" in result
    
    def test_investigations_independent_of_hints(self, temp_wiki):
        """Test that investigations are separate from hints."""
        temp_wiki.write_page("Company A", "# Company A\n\nRevenue: $10M\n")
        temp_wiki.write_page("Company B", "# Company B\n\nRevenue: $20M\n")
        
        result = temp_wiki.lint()
        
        # Hints and investigations should be independent
        assert isinstance(result["hints"]["critical"], list)
        assert isinstance(result["hints"]["informational"], list)
        assert isinstance(result["investigations"]["contradictions"], list)
        assert isinstance(result["investigations"]["data_gaps"], list)
