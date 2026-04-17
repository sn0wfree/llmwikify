"""Tests for CLI features added in v0.27.0: json format, fix-wikilinks, build-index --force."""

import json
import tempfile
from pathlib import Path

from llmwikify.cli.commands import WikiCLI
from llmwikify.core.wiki import Wiki


class Args:
    """Simple args namespace for testing."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_cli(temp_wiki):
    """Create a WikiCLI with a temp wiki."""
    cli = WikiCLI(temp_wiki)
    cli.wiki.init(overwrite=True)
    return cli


class TestLintJsonFormat:
    """Test lint --format json output."""

    def test_lint_json_output(self, temp_wiki):
        """--format json returns valid JSON with all lint fields."""
        cli = _make_cli(temp_wiki)

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        cli.lint(Args(format='json', generate_investigations=False, mode='check', limit=10, force=False))

        sys.stdout = old_stdout
        output = captured.getvalue()

        data = json.loads(output)
        assert 'total_pages' in data
        assert 'issue_count' in data
        assert 'issues' in data
        assert 'hints' in data

    def test_lint_json_with_broken_links(self, temp_wiki):
        """JSON output includes broken link issues."""
        cli = _make_cli(temp_wiki)

        concepts = cli.wiki.wiki_dir / 'concepts'
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / 'Risk Parity.md').write_text('# Risk Parity')

        broken_page = cli.wiki.wiki_dir / 'overview.md'
        broken_page.write_text('# Overview\n\n[[Risk Parity]]')

        cli.wiki.index.upsert_page('overview', broken_page.read_text(), 'overview.md')

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        cli.lint(Args(format='json', generate_investigations=False, mode='check', limit=10, force=False))

        sys.stdout = old_stdout
        output = captured.getvalue()

        data = json.loads(output)
        broken = [i for i in data['issues'] if i['type'] == 'broken_link']
        assert len(broken) >= 1
        assert broken[0]['link'] == 'Risk Parity'


class TestFixWikilinksCLI:
    """Test fix-wikilinks CLI command."""

    def test_fix_wikilinks_dry_run(self, temp_wiki):
        """--dry-run reports changes without modifying."""
        cli = _make_cli(temp_wiki)

        concepts = cli.wiki.wiki_dir / 'concepts'
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / 'Risk Parity.md').write_text('# Risk Parity')

        broken_page = cli.wiki.wiki_dir / 'overview.md'
        broken_page.write_text('# Overview\n\n[[Risk Parity]]')

        cli.wiki.index.upsert_page('overview', broken_page.read_text(), 'overview.md')

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        ret = cli.fix_wikilinks(Args(dry_run=True))

        sys.stdout = old_stdout
        output = captured.getvalue()

        assert ret == 0
        assert 'DRY RUN' in output
        assert 'Fixed:     1' in output

        # File not modified
        content = broken_page.read_text()
        assert '[[Risk Parity]]' in content

    def test_fix_wikilinks_actual_fix(self, temp_wiki):
        """Without --dry-run, fixes links."""
        cli = _make_cli(temp_wiki)

        concepts = cli.wiki.wiki_dir / 'concepts'
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / 'Risk Parity.md').write_text('# Risk Parity')

        broken_page = cli.wiki.wiki_dir / 'overview.md'
        broken_page.write_text('# Overview\n\n[[Risk Parity]]')

        cli.wiki.index.upsert_page('overview', broken_page.read_text(), 'overview.md')

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        ret = cli.fix_wikilinks(Args(dry_run=False))

        sys.stdout = old_stdout
        output = captured.getvalue()

        assert ret == 0
        assert 'FIXED' in output

        # File modified
        content = broken_page.read_text()
        assert '[[concepts/Risk Parity]]' in content


class TestBuildIndexForce:
    """Test build-index --force and old format detection."""

    def test_detect_old_format(self, temp_wiki):
        """_detect_old_index_format returns True when page_name != file_path[:-3]."""
        cli = _make_cli(temp_wiki)

        # Old format: page_name is bare but file_path has directory
        cli.wiki.index.upsert_page('Risk Parity', '# Risk Parity', 'concepts/Risk Parity.md')

        assert cli._detect_old_index_format() is True
        cli.wiki.close()

    def test_no_old_format_for_root_pages(self, temp_wiki):
        """Root pages (overview, log, index) are NOT flagged as old format."""
        cli = _make_cli(temp_wiki)

        # Root pages: page_name == file_path[:-3]
        cli.wiki.index.upsert_page('overview', '# Overview', 'overview.md')
        cli.wiki.index.upsert_page('log', '# Log', 'log.md')

        assert cli._detect_old_index_format() is False
        cli.wiki.close()

    def test_no_old_format_for_prefixed_pages(self, temp_wiki):
        """Prefixed pages are NOT flagged as old format."""
        cli = _make_cli(temp_wiki)

        # New format: page_name == file_path[:-3]
        cli.wiki.index.upsert_page('concepts/Risk Parity', '# Risk Parity', 'concepts/Risk Parity.md')
        cli.wiki.index.upsert_page('entities/Gold', '# Gold', 'entities/Gold.md')

        assert cli._detect_old_index_format() is False
        cli.wiki.close()

    def test_build_index_blocks_on_old_format(self, temp_wiki):
        """build-index returns 1 when old format detected without --force."""
        cli = _make_cli(temp_wiki)

        # Create old-format page
        cli.wiki.index.upsert_page('Risk Parity', '# Risk Parity', 'concepts/Risk Parity.md')

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        ret = cli.build_index(Args(no_export=True, output=None, export_only=False, force=False))

        sys.stdout = old_stdout
        output = captured.getvalue()

        assert ret == 1
        assert 'Old index format detected' in output

    def test_build_index_force_rebuild(self, temp_wiki):
        """build-index --force succeeds even with old format."""
        cli = _make_cli(temp_wiki)

        # Create old-format page
        cli.wiki.index.upsert_page('Risk Parity', '# Risk Parity', 'concepts/Risk Parity.md')

        import io, sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        ret = cli.build_index(Args(no_export=True, output=None, export_only=False, force=True))

        sys.stdout = old_stdout
        output = captured.getvalue()

        assert ret == 0
        assert 'Index Built' in output
        cli.wiki.close()
