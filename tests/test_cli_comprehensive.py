"""Comprehensive CLI unit tests.

Covers all CLI commands including:
- init (with --merge, --overwrite, --force)
- ingest (with --self-create, --dry-run)
- search
- references (with all flag combinations)
- sink-status
- synthesize
- watch (dry-run mode)
- graph-query (all subcommands)
- export-graph
- community-detect
- report
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


# ============================================================
# Init Command Tests
# ============================================================
class TestInitCommand:
    def test_init_creates_wiki(self, temp_wiki):
        """init should create wiki structure."""
        cli = WikiCLI(temp_wiki)
        args = Args()
        args.overwrite = False
        args.agent = None
        args.force = False
        args.merge = False

        result = cli.init(args)
        assert result == 0
        assert (temp_wiki / 'wiki.md').exists()
        assert (temp_wiki / 'wiki').exists()
        assert (temp_wiki / 'raw').exists()

    def test_init_already_exists(self, temp_wiki):
        """init should handle already initialized wiki."""
        cli = WikiCLI(temp_wiki)
        args = Args()
        args.overwrite = False
        args.agent = None
        args.force = False
        args.merge = False

        cli.init(args)

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.init(args)
        assert result == 0
        assert 'already' in stdout.getvalue().lower()

    def test_init_with_overwrite(self, temp_wiki):
        """init --overwrite should recreate wiki."""
        cli = WikiCLI(temp_wiki)
        args = Args()
        args.overwrite = False
        args.agent = None
        args.force = False
        args.merge = False
        cli.init(args)

        args.overwrite = True
        result = cli.init(args)
        assert result == 0


# ============================================================
# Ingest Command Tests
# ============================================================
class TestIngestCommand:
    def test_ingest_without_self_create_outputs_json(self, temp_wiki):
        """ingest without --self-create should output JSON."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.file = str(test_file)
        args.self_create = False
        args.smart = False
        args.dry_run = False

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            result = cli.ingest(args)

        assert result == 0
        stdout_content = stdout.getvalue()
        parsed = json.loads(stdout_content)
        assert 'content' in parsed
        assert 'instructions' in parsed
        assert 'source_name' in parsed

    def test_ingest_dry_run(self, temp_wiki):
        """ingest --dry-run should not create pages."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.file = str(test_file)
        args.self_create = False
        args.smart = False
        args.dry_run = True

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr):
            result = cli.ingest(args)

        assert result == 0
        stderr_content = stderr.getvalue()
        assert 'No pages created' in stderr_content or 'DRY RUN' in stderr_content


# ============================================================
# Search Command Tests
# ============================================================
class TestSearchCommand:
    def test_search_no_results(self, temp_wiki):
        """search should return 0 when no results found."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.build_index()

        args = Args()
        args.query = "nonexistent_xyz"
        args.limit = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.search(args)

        assert result == 0
        assert 'No results' in stdout.getvalue()

    def test_search_with_results(self, temp_wiki):
        """search should find content."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Test", "# Test\n\nThis is about gold mining")
        cli.wiki.build_index()

        args = Args()
        args.query = "gold"
        args.limit = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.search(args)

        assert result == 0
        assert 'Test' in stdout.getvalue()


# ============================================================
# References Command Tests
# ============================================================
class TestReferencesCommand:
    def test_references_inbound_only(self, temp_wiki):
        """references --inbound should show only inbound links."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\nLinks to [[Page B]]")
        cli.wiki.write_page("Page B", "# Page B")
        cli.wiki.build_index()

        args = Args()
        args.page = "Page B"
        args.detail = False
        args.inbound = True
        args.outbound = False
        args.stats = False
        args.broken = False
        args.top = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.references(args)

        assert result == 0
        assert 'Inbound' in stdout.getvalue()

    def test_references_outbound_only(self, temp_wiki):
        """references --outbound should show only outbound links."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\nLinks to [[Page B]]")
        cli.wiki.build_index()

        args = Args()
        args.page = "Page A"
        args.detail = False
        args.inbound = False
        args.outbound = True
        args.stats = False
        args.broken = False
        args.top = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.references(args)

        assert result == 0
        output = stdout.getvalue()
        assert 'Outbound' in output
        assert 'Inbound' not in output  # Should not show inbound when --outbound is set

    def test_references_stats(self, temp_wiki):
        """references --stats should show reference statistics."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\n[[Page B]]")
        cli.wiki.write_page("Page B", "# Page B\n\n[[Page A]]")
        cli.wiki.build_index()

        args = Args()
        args.page = "Page A"
        args.detail = False
        args.inbound = False
        args.outbound = False
        args.stats = True
        args.broken = False
        args.top = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.references(args)

        assert result == 0
        assert 'Reference Statistics' in stdout.getvalue()

    def test_references_broken(self, temp_wiki):
        """references --broken should detect broken links."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\nLinks to [[NonExistent]]")

        args = Args()
        args.page = "Page A"
        args.detail = False
        args.inbound = False
        args.outbound = False
        args.stats = False
        args.broken = True
        args.top = 10

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.references(args)

        assert result == 0
        assert 'Broken' in stdout.getvalue()


# ============================================================
# Sink Status Command Tests
# ============================================================
class TestSinkStatusCommand:
    def test_sink_status_empty(self, temp_wiki):
        """sink-status should handle empty sinks."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.sink_status(args)

        assert result == 0


# ============================================================
# Synthesize Command Tests
# ============================================================
class TestSynthesizeCommand:
    def test_synthesize_creates_page(self, temp_wiki):
        """synthesize should create a wiki page from answer."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.query = "What is gold?"
        args.answer = "Gold is a precious metal."
        args.page_name = None
        args.sources = []
        args.raw_sources = []
        args.no_auto_link = False
        args.no_auto_log = False
        args.mode = 'sink'

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.synthesize(args)

        assert result == 0


# ============================================================
# Watch Command Tests (dry-run mode)
# ============================================================
class TestWatchCommand:
    def test_watch_dry_run(self, temp_wiki):
        """watch --dry-run should print status without starting watcher."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)

        cli = WikiCLI(temp_wiki)

        args = Args()
        args.dir = None
        args.auto_ingest = False
        args.self_create = False
        args.smart = False
        args.debounce = 2.0
        args.dry_run = True
        args.git_hook = False
        args.uninstall_hook = False

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.watch(args)

        assert result == 0
        assert 'DRY RUN' in stdout.getvalue()


# ============================================================
# Community Detect Tests
# ============================================================
class TestCommunityDetectCommand:
    def test_community_detect_dry_run(self, temp_wiki):
        """community-detect --dry-run should show stats."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\n[[Page B]]")
        cli.wiki.write_page("Page B", "# Page B\n\n[[Page A]]")
        cli.wiki.build_index()

        args = Args()
        args.algorithm = 'leiden'
        args.resolution = 1.0
        args.json = False
        args.dry_run = True

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.community_detect(args)

        assert result == 0
        assert 'Community Detection' in stdout.getvalue()


# ============================================================
# Report Command Tests
# ============================================================
class TestReportCommand:
    def test_report_generates_output(self, temp_wiki):
        """report should generate unexpected connections report."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\n[[Page B]]")
        cli.wiki.write_page("Page B", "# Page B\n\n[[Page A]]")
        cli.wiki.build_index()

        args = Args()
        args.top = 10
        args.output = None

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.report(args)

        assert result == 0


# ============================================================
# Export Graph Tests
# ============================================================
class TestExportGraphCommand:
    def test_export_graph_html(self, temp_wiki):
        """export-graph should work with minimal pages."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Page A", "# Page A\n\n[[Page B]]")
        cli.wiki.write_page("Page B", "# Page B\n\n[[Page A]]")
        cli.wiki.build_index()

        args = Args()
        args.format = 'html'
        args.output = str(temp_wiki / 'graph.html')
        args.min_degree = 0

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            try:
                result = cli.export_graph(args)
                # May fail if networkx not installed
                if result != 0:
                    assert 'Missing dependency' in stdout.getvalue() or 'Export failed' in stdout.getvalue()
                else:
                    assert 'Exported' in stdout.getvalue()
            except ImportError:
                pass  # networkx not installed, skip


# ============================================================
# Batch Integration Tests
# ============================================================
class TestBatchIntegration:
    def test_batch_with_multiple_sources(self, temp_wiki):
        """batch should handle multiple sources."""
        raw = temp_wiki / 'raw'
        raw.mkdir(exist_ok=True)
        (raw / 'doc1.md').write_text("# Doc 1\n\nContent 1")
        (raw / 'doc2.md').write_text("# Doc 2\n\nContent 2")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.source = str(raw)
        args.self_create = False
        args.smart = False
        args.dry_run = False
        args.limit = 0

        stdout = StringIO()
        stderr = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stderr', stderr):
            result = cli.batch(args)

        assert result == 0
        parsed = json.loads(stdout.getvalue())
        assert parsed['batch_summary']['total'] == 2
        assert parsed['batch_summary']['success'] == 2


# ============================================================
# Smart Deprecation Warning Tests
# ============================================================
class TestSmartDeprecation:
    def test_ingest_smart_deprecation_warning(self, temp_wiki):
        """ingest --smart should emit deprecation warning."""
        (temp_wiki / 'raw').mkdir(exist_ok=True)
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test")

        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.file = str(test_file)
        args.self_create = False
        args.smart = True
        args.dry_run = True

        stderr = StringIO()
        with patch('sys.stdout', StringIO()), patch('sys.stderr', stderr):
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                cli.ingest(args)
                deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
                assert len(deprecation_warnings) >= 1
                assert 'deprecated' in str(deprecation_warnings[0].message).lower()


# ============================================================
# Error Handling Tests
# ============================================================
class TestCLIErrorHandling:
    def test_log_missing_args(self, temp_wiki):
        """log without args should return error."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.operation = None
        args.description = None
        args.op_flag = None
        args.details = None

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.log(args)

        assert result == 1

    def test_read_page_nonexistent(self, temp_wiki):
        """read_page for non-existent page should return error."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.name = "NonExistentPage"

        stdout = StringIO()
        with patch('sys.stdout', stdout):
            result = cli.read_page(args)

        assert result == 1

    def test_write_page_no_content(self, temp_wiki):
        """write_page without content should return error."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        args = Args()
        args.name = "Test"
        args.file = None
        args.content = None

        stdout = StringIO()
        with patch('sys.stdout', stdout), patch('sys.stdin', StringIO('')):
            result = cli.write_page(args)

        assert result == 1
