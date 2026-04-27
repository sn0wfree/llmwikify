"""Unit tests for unified web UI server module."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestUnifiedServer:
    """Test unified server module."""

    def test_unified_server_imports(self):
        """Unified server module should import without errors."""
        from llmwikify.mcp.server import create_unified_server
        assert create_unified_server is not None

    def test_web_server_imports(self):
        """Web server wrapper should import without errors."""
        from llmwikify.web.server import main
        assert main is not None

    def test_webui_static_files_exist(self):
        """React WebUI build files should exist."""
        webui_dist = Path(__file__).parent.parent / 'src' / 'llmwikify' / 'web' / 'webui' / 'dist'
        if webui_dist.exists():
            assert (webui_dist / 'index.html').exists()

    def test_legacy_static_dir_exists(self):
        """Legacy static directory should exist."""
        static_dir = Path(__file__).parent.parent / 'src' / 'llmwikify' / 'web' / 'static'
        assert static_dir.exists()


class TestCLIWebArgs:
    """Test CLI web arguments."""

    def test_serve_help_not_contains_agent(self):
        """serve --help should NOT mention --agent (deprecated)."""
        import io
        from unittest.mock import patch

        from llmwikify.cli.commands import main

        help_output = io.StringIO()
        with patch('sys.argv', ['llmwikify', 'serve', '--help']):
            with patch('sys.stdout', help_output):
                with pytest.raises(SystemExit):
                    main()

        output = help_output.getvalue()
        assert '--agent' not in output
