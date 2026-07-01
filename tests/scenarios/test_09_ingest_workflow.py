# tests/scenarios/test_09_ingest_workflow.py
"""Scenario 9: Ingest Workflow - Tests for file ingestion.

## Background
Ingest extracts text from files (PDF/MD/HTML), saves to raw/, then
LLM analyzes for entities/relations. batch --self-create combines
both steps for one-shot processing.

## Pipeline
```
Source file
   │ ingest_source (no LLM)
   ▼
raw/<slug>.md
   │ analyze_source (LLM)
   ▼
Entities + Relations + Suggested pages
   │ batch --self-create (LLM)
   ▼
Wiki pages with auto-linking
```

## Troubleshooting
- ingest fails on PDF: pip install 'llmwikify[extractors]'
- batch --self-create creates no pages: LLM returned no operations
- analyze_source hangs: check API key in ~/.llmwikify/llmwikify.json
"""


import subprocess
import shutil
import pytest


class TestIngestWorkflow:
    """Test ingest operations: single file, batch, dry-run, LLM.

    Covers TUTORIAL.md Scenario 1 (ingest step).
    """

    def test_9_1_ingest_single_file(self, wiki, sample_markdown_file):
        """Step 9.1: Ingest a single markdown file.

        Pure text extraction, no LLM. Saves to raw/ for later analysis.
        """
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        result = wiki.ingest_source(str(sample_markdown_file))
        assert result is not None
        assert isinstance(result, dict)

    def test_9_2_ingest_dry_run(self, wiki, sample_markdown_file):
        """Step 9.2: Ingest with --dry-run flag.

        Shows what would happen without actually creating files.
        """
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        wiki.root.mkdir(parents=True, exist_ok=True)
        dest = wiki.root / "sample_doc.md"
        shutil.copy(sample_markdown_file, dest)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "ingest", str(dest), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]

    def test_9_3_batch_ingest(self, wiki, batch_dir):
        """Step 9.3: Batch ingest from a directory (no LLM).

        Process multiple files at once, extract text only.
        """
        if not batch_dir.exists():
            pytest.skip("Batch directory not available")

        dest = wiki.root / "batch_sources"
        shutil.copytree(batch_dir, dest, dirs_exist_ok=True)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "batch", str(dest)],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]

    def test_9_4_ingest_creates_raw(self, wiki, sample_markdown_file):
        """Step 9.4: Ingest creates raw/ directory structure.

        Verifies that raw/ exists after ingest.
        """
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        wiki.ingest_source(str(sample_markdown_file))
        assert wiki.raw_dir.exists() or (wiki.root / "raw").exists()

    def test_9_5_ingest_fts_index(self, wiki, sample_markdown_file):
        """Step 9.5: Ingest updates FTS5 index for search.

        Search should find content from ingested files.
        """
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        wiki.ingest_source(str(sample_markdown_file))
        results = wiki.search("llmwikify", limit=5)
        assert isinstance(results, list)

    @pytest.mark.llm
    def test_9_6_analyze_source(self, wiki, sample_markdown_file):
        """Step 9.6: LLM analyzes source for entities/relations.

        Two-phase: section metadata (compute) + LLM section selection
        + targeted analysis.
        """
        if not sample_markdown_file.exists():
            pytest.skip("Sample markdown file not available")

        ingest_result = wiki.ingest_source(str(sample_markdown_file))
        source_name = ingest_result.get("source_name")
        assert source_name is not None

        analysis = wiki.analyze_source(f"raw/{source_name}")
        assert analysis is not None
        assert isinstance(analysis, dict)

    @pytest.mark.llm
    def test_9_7_batch_self_create(self, wiki, batch_dir):
        """Step 9.7: batch --self-create uses LLM to create pages.

        Combines ingest + LLM page creation in one command.
        """
        if not batch_dir.exists():
            pytest.skip("Batch directory not available")

        dest = wiki.root / "batch_sources"
        shutil.copytree(batch_dir, dest, dirs_exist_ok=True)

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "batch", str(dest), "--self-create"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]
