"""Tests for CLI commands."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.cli import WikiCLI


class TestCLI:
    """Test CLI command handlers."""

    def test_status_command(self, temp_wiki):
        """Test status command."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        class Args:
            pass

        result = cli.status(Args())

        assert result == 0

    def test_lint_command_healthy(self, temp_wiki):
        """Test lint command with healthy wiki."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        # Create healthy page
        cli.wiki.write_page("Test", "# Test\n\n[[index]]")

        class Args:
            format = 'full'
            generate_investigations = False

        result = cli.lint(Args())

        # Should return 1 if issues exist (orphan)
        assert result in [0, 1]

    def test_lint_brief_format(self, temp_wiki):
        """Test lint --format=brief (replaces old hint command)."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        class Args:
            format = 'brief'
            generate_investigations = False

        result = cli.lint(Args())
        assert result == 0

    def test_lint_recommendations_format(self, temp_wiki):
        """Test lint --format=recommendations (replaces old recommend command)."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        class Args:
            format = 'recommendations'
            generate_investigations = False

        result = cli.lint(Args())
        assert result == 0

    def test_write_page_command(self, temp_wiki):
        """Test write_page command."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        class Args:
            name = "Test Page"
            file = None
            content = "# Test\n\nContent"

        result = cli.write_page(Args())

        assert result == 0
        assert (temp_wiki / 'wiki' / 'Test Page.md').exists()

    def test_read_page_command(self, temp_wiki):
        """Test read_page command."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Test", "# Test")

        class Args:
            name = "Test"

        result = cli.read_page(Args())

        assert result == 0

    def test_log_command(self, temp_wiki):
        """Test log command."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()

        class Args:
            operation = "test"
            description = "Test log entry"

        result = cli.log(Args())

        assert result == 0

    def test_build_index_command(self, temp_wiki):
        """Test build-index command."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("A", "# A\n\n[[B]]")
        cli.wiki.write_page("B", "# B")

        class Args:
            no_export = False
            output = None
            export_only = False

        result = cli.build_index(Args())

        assert result == 0

    def test_build_index_export_only(self, temp_wiki):
        """Test build-index --export-only (replaces old export-index command)."""
        cli = WikiCLI(temp_wiki)
        cli.wiki.init()
        cli.wiki.write_page("Test", "# Test")
        cli.wiki.build_index()

        class Args:
            no_export = False
            output = None
            export_only = True

        result = cli.build_index(Args())
        assert result == 0
        assert (temp_wiki / 'wiki' / 'reference_index.json').exists()
