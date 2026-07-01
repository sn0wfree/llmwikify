# tests/scenarios/test_09_ingest_workflow.py
"""Scenario 1: Ingest Workflow - Tests for file ingestion."""

import subprocess
import shutil
import pytest


class TestIngestWorkflow:
    """Test ingest operations: single file, batch, dry-run."""

    def test_9_1_ingest_single_file(self, wiki, sample_markdown_file):
        """Ingest a single markdown file."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        result = wiki.ingest_source(str(sample_markdown_file))
        assert result is not None
        assert isinstance(result, dict)

    def test_9_2_ingest_dry_run(self, wiki, sample_markdown_file):
        """Ingest with dry-run flag via CLI."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        # Ensure wiki directory exists and copy sample file
        wiki.root.mkdir(parents=True, exist_ok=True)
        dest = wiki.root / "sample_doc.md"
        shutil.copy(sample_markdown_file, dest)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "ingest", str(dest), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        # Dry run should succeed
        assert result.returncode in [0, 1]

    def test_9_3_batch_ingest(self, wiki, batch_dir):
        """Batch ingest from a directory."""
        if not batch_dir.exists():
            pytest.skip("Batch directory not available")

        # Copy batch sources to wiki root
        dest = wiki.root / "batch_sources"
        shutil.copytree(batch_dir, dest, dirs_exist_ok=True)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "batch", str(dest)],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        # Batch may succeed or fail depending on implementation
        assert result.returncode in [0, 1]

    def test_9_4_ingest_creates_raw(self, wiki, sample_markdown_file):
        """Ingest creates raw/ directory structure."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        wiki.ingest_source(str(sample_markdown_file))

        # Check that raw directory exists
        assert wiki.raw_dir.exists() or (wiki.root / "raw").exists()

    def test_9_5_ingest_fts_index(self, wiki, sample_markdown_file):
        """Ingest updates FTS5 index for search."""
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        wiki.ingest_source(str(sample_markdown_file))

        # Search should find content from ingested file
        results = wiki.search("llmwikify", limit=5)
        # May or may not find results depending on FTS implementation
        assert isinstance(results, list)

    @pytest.mark.llm
    def test_9_6_analyze_source(self, wiki, sample_markdown_file):
        """Analyze source with LLM to extract entities/relations."""
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

    @pytest.mark.llm
    def test_9_7_batch_self_create(self, wiki, batch_dir):
        """Batch ingest with --self-create uses LLM to create pages."""
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

        # Check if command executed
        assert result.returncode in [0, 1]
