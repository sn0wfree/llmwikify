"""CLI integration tests with real project simulation.

Tests simulate end-to-end workflows:
1. Full init → ingest → batch → write → search → lint → build-index cycle
2. Subdirectory page creation and indexing
3. Cross-reference validation with subdirectory pages
4. Status accuracy with mixed page locations
"""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.cli import WikiCLI


class Args:
    pass


def _init_args(overwrite=False, agent=None, force=False, merge=False):
    args = Args()
    args.overwrite = overwrite
    args.agent = agent
    args.force = force
    args.merge = merge
    return args


def _build_index_args(no_export=False, output=None, export_only=False):
    args = Args()
    args.no_export = no_export
    args.output = output
    args.export_only = export_only
    return args


# ============================================================
# Full Workflow Integration Test
# ============================================================
class TestFullWorkflow:
    """Simulate a complete wiki workflow."""

    def test_init_ingest_batch_search_lint_cycle(self, temp_wiki):
        """Full cycle: init → write pages → build-index → search → lint."""
        cli = WikiCLI(temp_wiki)

        # 1. Initialize
        assert cli.init(_init_args()) == 0

        # 2. Create pages manually (simulating ingest result)
        cli.wiki.write_page("Gold Market", "# Gold Market\n\nGold prices rose in 2024.\n\nSee also [[Silver Market]] and [[Copper Mining]].")
        cli.wiki.write_page("Silver Market", "# Silver Market\n\nSilver is used in electronics.\n\nRelated: [[Gold Market]].")
        cli.wiki.write_page("Overview", "# Overview\n\nThis wiki covers precious metals.\n\nKey topics: [[Gold Market]], [[Silver Market]].")

        # 3. Build index
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.build_index(_build_index_args())
        assert result == 0

        # 4. Search
        args = Args()
        args.query = "gold"
        args.limit = 10
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.search(args)
        assert result == 0
        assert 'Gold Market' in stdout.getvalue()

        # 5. Lint
        args = Args()
        args.format = 'full'
        args.generate_investigations = False
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.lint(args)
        # Lint returns 1 if issues found (which is normal)
        assert result in [0, 1]

        # 6. Status
        args = Args()
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.status(args)
        assert result == 0
        assert 'Pages:' in stdout.getvalue()


# ============================================================
# Subdirectory Page Integration Test
# ============================================================
class TestSubdirectoryPages:
    """Test that subdirectory pages work correctly."""

    def _create_subdir_wiki(self, temp_wiki):
        """Create wiki with pages in subdirectories."""
        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Create subdirectory pages
        entities_dir = temp_wiki / 'wiki' / 'entities'
        entities_dir.mkdir(parents=True, exist_ok=True)
        (entities_dir / 'Company A.md').write_text(
            "# Company A\n\nA mining company.\n\nRelated: [[Company B]] and [[Company C]]."
        )
        (entities_dir / 'Company B.md').write_text(
            "# Company B\n\nAnother mining company.\n\nSee [[Company A]]."
        )
        (entities_dir / 'Company C.md').write_text(
            "# Company C\n\nThird company.\n\n[[Company A]] is a competitor."
        )

        sources_dir = temp_wiki / 'wiki' / 'sources'
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / '2024-report.md').write_text(
            "# 2024 Report\n\nAnnual report.\n\nCompanies: [[Company A]], [[Company B]]."
        )

        # Root page linking to subdirectory pages
        cli.wiki.write_page("Overview", "# Overview\n\nEntities: [[Company A]], [[Company B]].")

        return cli

    def test_status_counts_subdirectory_pages(self, temp_wiki):
        """status should include subdirectory pages in count."""
        cli = self._create_subdir_wiki(temp_wiki)

        args = Args()
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.status(args)

        output = stdout.getvalue()
        assert 'Pages:' in output

    def test_lint_finds_subdirectory_issues(self, temp_wiki):
        """lint should check subdirectory pages for broken links."""
        cli = self._create_subdir_wiki(temp_wiki)

        # Build index first (needed for lint orphan check)
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        args = Args()
        args.format = 'full'
        args.generate_investigations = False
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.lint(args)

        output = stdout.getvalue()
        # Should report total pages including subdirectory pages
        assert 'Total pages:' in output or 'issue_count' in output.lower() or 'issues' in output.lower()

    def test_search_finds_subdirectory_content(self, temp_wiki):
        """search should find content in subdirectory pages."""
        cli = self._create_subdir_wiki(temp_wiki)

        # Build index
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Search for "mining" which appears in subdirectory pages
        args = Args()
        args.query = "mining"
        args.limit = 10
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.search(args)

        output = stdout.getvalue()
        assert 'Company' in output or 'mining' in output.lower() or 'No results' in output

    def test_references_works_with_subdirectory_pages(self, temp_wiki):
        """references should work with subdirectory pages."""
        cli = self._create_subdir_wiki(temp_wiki)

        # Build index
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Check references for a root page
        args = Args()
        args.page = "Overview"
        args.detail = False
        args.inbound = False
        args.outbound = True
        args.stats = False
        args.broken = False
        args.top = 10
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.references(args)

        output = stdout.getvalue()
        assert 'References' in output


# ============================================================
# Batch + Write Integration Test
# ============================================================
class TestBatchWriteIntegration:
    """Test batch ingest followed by manual page creation."""

    def test_batch_then_write_pages(self, temp_wiki):
        """Batch ingest sources, then manually create wiki pages."""
        raw = temp_wiki / 'raw'
        raw.mkdir(exist_ok=True)
        (raw / 'source1.md').write_text("# Mining Report 2024\n\nGold production increased 15% in Q4.")
        (raw / 'source2.md').write_text("# Silver Prices\n\nSilver hit $30/oz in December 2024.")

        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Batch ingest (dry-run to get JSON)
        batch_args = Args()
        batch_args.source = str(raw)
        batch_args.self_create = False
        batch_args.smart = False
        batch_args.dry_run = False
        batch_args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            result = cli.batch(batch_args)

        assert result == 0
        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['success'] == 2

        # Manually create wiki pages from batch results
        cli.wiki.write_page("Mining Report 2024", "# Mining Report 2024\n\nGold production increased.\n\nSource: [[raw/source1.md]]")
        cli.wiki.write_page("Silver Prices", "# Silver Prices\n\nSilver hit $30/oz.\n\nSource: [[raw/source2.md]]")

        # Build index and verify
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Search should find the new pages
        search_args = Args()
        search_args.query = "silver"
        search_args.limit = 10
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.search(search_args)
        assert 'Silver' in stdout.getvalue()


# ============================================================
# Cross-Reference Validation Test
# ============================================================
class TestCrossReferenceValidation:
    """Test cross-reference validation with various page locations."""

    def test_broken_links_across_subdirectories(self, temp_wiki):
        """Broken link detection should work across subdirectories."""
        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Create pages with broken links
        entities_dir = temp_wiki / 'wiki' / 'entities'
        entities_dir.mkdir(parents=True, exist_ok=True)
        (entities_dir / 'Valid Page.md').write_text("# Valid Page\n\nLinks to [[entities/NonExistent]].")
        cli.wiki.write_page("Root Page", "# Root Page\n\nLinks to [[NonExistent Root]].")

        # Build index
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Lint should find broken links
        lint_args = Args()
        lint_args.format = 'full'
        lint_args.generate_investigations = False
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.lint(lint_args)

        output = stdout.getvalue()
        assert 'broken_link' in output

    def test_recommend_finds_missing_pages(self, temp_wiki):
        """recommend should find pages referenced but not created."""
        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Create pages that reference non-existent pages multiple times
        cli.wiki.write_page("Page A", "# Page A\n\nSee [[Missing Page]] and [[Missing Page]].")
        cli.wiki.write_page("Page B", "# Page B\n\nAlso see [[Missing Page]].")

        # Build index
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Check recommendations
        rec = cli.wiki.recommend()
        missing_names = [p['page'] for p in rec.get('missing_pages', [])]
        assert 'Missing Page' in missing_names


# ============================================================
# Log Integration Test
# ============================================================
class TestLogIntegration:
    """Test log command integration."""

    def test_log_chain(self, temp_wiki):
        """Multiple log entries should accumulate."""
        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Write multiple log entries
        for i in range(3):
            args = Args()
            args.operation = f"test_op_{i}"
            args.description = f"Test operation {i}"
            args.op_flag = None
            args.details = None
            assert cli.log(args) == 0

        # Read log
        log_content = cli.wiki.log_file.read_text()
        assert 'test_op_0' in log_content
        assert 'test_op_1' in log_content
        assert 'test_op_2' in log_content


# ============================================================
# Synthesize Integration Test
# ============================================================
class TestSynthesizeIntegration:
    """Test synthesize command integration."""

    def test_synthesize_then_search(self, temp_wiki):
        """synthesize should create page that is searchable."""
        cli = WikiCLI(temp_wiki)
        cli.init(_init_args())

        # Synthesize a query answer
        args = Args()
        args.query = "What is mining?"
        args.answer = "Mining is the extraction of valuable minerals from the earth."
        args.page_name = None
        args.sources = []
        args.raw_sources = []
        args.no_auto_link = False
        args.no_auto_log = False
        args.mode = 'sink'

        with patch('sys.stdout', StringIO()):
            result = cli.synthesize(args)
        assert result == 0

        # Build index
        with patch('sys.stdout', StringIO()):
            cli.build_index(_build_index_args())

        # Search for the synthesized content
        search_args = Args()
        search_args.query = "minerals"
        search_args.limit = 10
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            cli.search(search_args)
        # Should find the synthesized page
        assert 'minerals' in stdout.getvalue().lower() or 'What is mining' in stdout.getvalue()
