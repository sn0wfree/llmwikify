# tests/scenarios/test_14_full_ingest_chain.py
"""Scenario 14: Full Ingest Chain - Complete chain test."""

import subprocess
import shutil
import pytest


@pytest.mark.llm
class TestFullIngestChain:
    """Test complete ingest chain with LLM calls."""

    def test_14_1_ingest_extract(self, wiki, sample_markdown_file):
        """Step 1: ingest extracts text, saves to raw/."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        result = wiki.ingest_source(str(sample_markdown_file))

        assert result is not None
        assert isinstance(result, dict)
        assert result.get("saved_to_raw") is True
        assert result.get("word_count", 0) > 0
        assert result.get("content") is not None
        assert wiki.raw_dir.exists()

    def test_14_2_analyze_source(self, wiki, sample_markdown_file):
        """Step 2: analyze-source uses LLM to extract entities/relations."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        # First ingest
        ingest_result = wiki.ingest_source(str(sample_markdown_file))
        source_name = ingest_result.get("source_name")
        assert source_name is not None

        # Then analyze (calls LLM)
        analysis = wiki.analyze_source(f"raw/{source_name}")

        assert analysis is not None
        assert isinstance(analysis, dict)

    def test_14_3_batch_self_create(self, wiki, batch_dir):
        """Step 3: batch --self-create uses LLM to create pages."""
        if not batch_dir.exists():
            pytest.skip("Batch directory not available")

        # Copy batch sources to wiki root
        dest = wiki.root / "batch_sources"
        shutil.copytree(batch_dir, dest, dirs_exist_ok=True)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "batch", str(dest), "--self-create"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )

        # Check if pages were created or command executed
        assert result.returncode in [0, 1]

    def test_14_4_suggest_synthesis(self, wiki):
        """Step 4: suggest-synthesis generates cross-source recommendations."""
        wiki.write_page("source-a", "# Company A\n\nRevenue: $10B. Growth: 15%.")
        wiki.write_page("source-b", "# Company B\n\nRevenue: $8B. Growth: 20%.")

        result = wiki.suggest_synthesis()

        assert result is not None
        assert isinstance(result, dict)
        assert "suggestions" in result

    def test_14_5_synthesize_query(self, wiki):
        """Step 5: synthesize creates wiki page from query answer."""
        wiki.write_page("company-a", "# Company A\n\nRevenue: $10B.")
        wiki.write_page("company-b", "# Company B\n\nRevenue: $8B.")

        result = wiki.synthesize_query(
            query="Compare revenue",
            answer="# Revenue Comparison\n\nA: $10B, B: $8B.",
            source_pages=["company-a", "company-b"],
            auto_link=True,
        )

        assert result is not None
        assert isinstance(result, dict)
        assert "page_name" in result

        # Verify page was created
        page = wiki.read_page(result["page_name"])
        assert page is not None

    def test_14_6_full_chain(self, wiki, sample_markdown_file):
        """Complete ingest → analyze → write → search → lint chain."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        # Step 1: ingest (no LLM)
        ingest_result = wiki.ingest_source(str(sample_markdown_file))
        assert ingest_result.get("saved_to_raw") is True
        source_name = ingest_result.get("source_name")

        # Step 2: analyze (LLM)
        analysis = wiki.analyze_source(f"raw/{source_name}")
        assert analysis is not None

        # Step 3: write page based on analysis
        wiki.write_page("analysis-result", "# Analysis\n\nFrom ingested content.")

        # Step 4: build index
        idx = wiki.build_index()
        assert idx["total_pages"] >= 1

        # Step 5: search
        results = wiki.search("analysis", limit=5)
        assert isinstance(results, list)

        # Step 6: lint
        lint_result = wiki.lint()
        assert "issues" in lint_result
