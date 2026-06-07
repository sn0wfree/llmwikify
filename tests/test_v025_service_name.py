"""Unit tests for v0.25 service name auto-detection feature.

Covers:
- create_mcp_server() name resolution priority chain
- serve_mcp() passthrough and logging
- CLI argument parsing (--name / -n)
- CLI serve() method integration
- Config file integration (.wiki-config.yaml mcp.name)
- Edge cases (special chars, unicode, empty, etc.)
- FastMCP integration (mcp.name attribute)
"""

import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def _run_async(coro):
    """Run async coroutine, handling nested event loop issues."""
    import asyncio
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        raise


from llmwikify.interfaces.cli import WikiCLI
from llmwikify.core import Wiki
from llmwikify.interfaces.mcp.server import create_mcp_server, serve_mcp


class Args:
    pass


# ============================================================
# TestCreateMCPNameResolution — 1.1 to 1.7
# ============================================================
class TestCreateMCPNameResolution:
    """Test service name resolution in create_mcp_server()."""

    @pytest.fixture
    def wiki(self, tmp_path):
        w = Wiki(tmp_path)
        w.init()
        yield w
        w.close()

    def test_default_takes_directory_name(self, wiki, tmp_path):
        """1.1: Without name or config, should use directory name."""
        mcp = create_mcp_server(wiki)
        assert mcp.name == tmp_path.name

    def test_name_parameter_override(self, wiki):
        """1.2: name parameter should override directory name."""
        mcp = create_mcp_server(wiki, name='my-wiki')
        assert mcp.name == 'my-wiki'

    def test_config_name_override(self, wiki):
        """1.3: config['name'] should override directory name."""
        mcp = create_mcp_server(wiki, config={'name': 'cfg-wiki'})
        assert mcp.name == 'cfg-wiki'

    def test_priority_name_over_config(self, wiki):
        """1.4: name parameter wins over config['name']."""
        mcp = create_mcp_server(
            wiki, name='cli-wiki', config={'name': 'cfg-wiki'}
        )
        assert mcp.name == 'cli-wiki'

    def test_priority_config_over_directory(self, wiki, tmp_path):
        """1.5: config['name'] wins over directory name."""
        mcp = create_mcp_server(wiki, config={'name': 'cfg-wiki'})
        assert mcp.name == 'cfg-wiki'
        assert mcp.name != tmp_path.name

    def test_empty_string_name_falls_back_to_directory(self, wiki, tmp_path):
        """1.6: Empty string name should fall back to directory name."""
        mcp = create_mcp_server(wiki, name='')
        assert mcp.name == tmp_path.name

    def test_none_config_no_error(self, wiki, tmp_path):
        """1.7: config=None should not error, use directory name."""
        mcp = create_mcp_server(wiki, config=None)
        assert mcp.name == tmp_path.name


# ============================================================
# TestServeMCPPassthrough — 2.1 to 2.4
# ============================================================
class TestServeMCPPassthrough:
    """Test serve_mcp() name passthrough and logging."""

    @pytest.fixture
    def wiki(self, tmp_path):
        w = Wiki(tmp_path)
        w.init()
        yield w
        w.close()

    def test_name_passed_to_create_mcp_server(self, wiki):
        """2.1: serve_mcp should pass name to MCPAdapter."""
        with patch('llmwikify.mcp.adapter.MCPAdapter') as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.name = 'test-wiki'
            mock_adapter_cls.return_value = mock_adapter

            with patch('asyncio.run'):
                serve_mcp(wiki, name='test-wiki')
                mock_adapter_cls.assert_called_once_with(wiki, name='test-wiki', config=None)

    def test_stdio_log_contains_service_name(self, wiki, tmp_path):
        """2.2: stdio mode should call MCPAdapter with correct name."""
        with patch('llmwikify.mcp.adapter.MCPAdapter') as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.name = 'my-wiki'
            mock_adapter_cls.return_value = mock_adapter

            with patch('asyncio.run'):
                serve_mcp(wiki, name='my-wiki', transport='stdio')
                mock_adapter_cls.assert_called_once_with(wiki, name='my-wiki', config=None)

    def test_http_log_contains_service_name(self, wiki, tmp_path):
        """2.3: http mode should call MCPAdapter with correct name."""
        with patch('llmwikify.mcp.adapter.MCPAdapter') as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.name = 'http-wiki'
            mock_adapter_cls.return_value = mock_adapter

            with patch('asyncio.run'):
                serve_mcp(wiki, name='http-wiki', transport='http')
                mock_adapter_cls.assert_called_once_with(wiki, name='http-wiki', config=None)

    def test_no_name_uses_directory_name_in_log(self, wiki, tmp_path):
        """2.4: When no name provided, MCPAdapter should use directory name."""
        with patch('llmwikify.mcp.adapter.MCPAdapter') as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.name = tmp_path.name
            mock_adapter_cls.return_value = mock_adapter

            with patch('asyncio.run'):
                serve_mcp(wiki, transport='stdio')
                call_kwargs = mock_adapter_cls.call_args.kwargs
                assert call_kwargs['name'] is None


# ============================================================
# TestCLIArgParsing — 3.1 to 3.5
# ============================================================
class TestCLIArgParsing:
    """Test CLI argument parsing for --name."""

    def test_name_long_parameter(self):
        """3.1: --name long parameter should be parsed.

        Phase 3 #6 — use the parser directly (not main()) to
        verify argparse parsing without starting the MCP server.
        """
        from llmwikify.interfaces.cli._app import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["mcp", "--name", "testwiki"])
        assert args.name == "testwiki", (
            f"--name should parse to 'testwiki'. Got: {args.name!r}"
        )

    def test_name_short_parameter(self):
        """3.2: -n short parameter should be parsed.

        Phase 3 #6 — see test_name_long_parameter.
        """
        from llmwikify.interfaces.cli._app import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["mcp", "-n", "shortwiki"])
        assert args.name == "shortwiki", (
            f"-n should parse to 'shortwiki'. Got: {args.name!r}"
        )

    def test_mcp_help_contains_name(self):
        """3.3: mcp --help should mention --name."""
        from llmwikify.interfaces.cli.commands import main
        stdout = StringIO()
        with patch('sys.argv', ['llmwikify', 'mcp', '--help']):
            with patch('sys.stdout', stdout):
                with pytest.raises(SystemExit):
                    main()

        output = stdout.getvalue()
        assert '--name' in output
        assert '-n NAME' in output

    def test_serve_help_contains_name(self):
        """3.4: serve --help should mention --name."""
        from llmwikify.interfaces.cli.commands import main
        stdout = StringIO()
        with patch('sys.argv', ['llmwikify', 'serve', '--help']):
            with patch('sys.stdout', stdout):
                with pytest.raises(SystemExit):
                    main()

        output = stdout.getvalue()
        assert '--name' in output

    def test_no_name_defaults_to_none(self):
        """3.5: Without --name, args.name should be None.

        Phase 3 #6 — use the parser directly.
        """
        from llmwikify.interfaces.cli._app import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["mcp"])
        assert args.name is None, (
            f"Without --name, args.name should be None. "
            f"Got: {args.name!r}"
        )


# ============================================================
# TestCLIServeMethod — 4.1 to 4.4
# ============================================================
class TestCLIServeMethod:
    """Test CLI serve() method integration."""

    @pytest.fixture
    def cli(self, temp_wiki):
        cli = WikiCLI(temp_wiki, config={'mcp': {'transport': 'stdio'}})
        cli.wiki.init()
        return cli

    def test_name_passed_to_serve_mcp(self, cli):
        """4.1: --name should be passed through to the MCP server.

        Phase 3 #6 — ``serve.py`` no longer imports
        ``llmwikify.mcp.server.serve_mcp`` (the deprecated
        shim). The stdio path now uses ``MCPAdapter``
        directly. We mock ``MCPAdapter`` to verify the
        ``name=`` kwarg flows through.
        """
        with patch('llmwikify.cli.commands.serve.MCPAdapter') as MockAdapter:
            mock_instance = MagicMock()
            MockAdapter.return_value = mock_instance

            # Patch asyncio.run so we don't actually start the server
            with patch('asyncio.run') as mock_asyncio:
                args = Args()
                args.name = 'cli-wiki'
                args.transport = None
                args.host = None
                args.port = None
                args.mcp_port = None
                args.web = False
                args.auth_token = None
                args.multi_wiki = False

                cli.serve(args)

                # MCPAdapter was constructed with the wiki + name
                MockAdapter.assert_called_once()
                call_kwargs = MockAdapter.call_args.kwargs
                assert call_kwargs.get('name') == 'cli-wiki', (
                    f"--name should reach MCPAdapter as name=. "
                    f"Got: {call_kwargs}"
                )

    def test_no_name_falls_back_to_none(self, cli):
        """4.2: Without --name, MCPAdapter receives name=None.

        Phase 3 #6 — see test_name_passed_to_serve_mcp.
        """
        cli.config['mcp']['name'] = None
        with patch('llmwikify.cli.commands.serve.MCPAdapter') as MockAdapter:
            mock_instance = MagicMock()
            MockAdapter.return_value = mock_instance

            with patch('asyncio.run'):
                args = Args()
                args.name = None
                args.transport = None
                args.host = None
                args.port = None
                args.mcp_port = None
                args.web = False
                args.auth_token = None
                args.multi_wiki = False

                cli.serve(args)

                call_kwargs = MockAdapter.call_args.kwargs
                assert call_kwargs.get('name') is None, (
                    f"Without --name and no config, MCPAdapter should "
                    f"get name=None. Got: {call_kwargs}"
                )

    def test_startup_log_prints_service_name(self, cli, temp_wiki):
        """4.3: Startup log should print service name.

        Phase 3 #6 — see test_name_passed_to_serve_mcp.
        """
        with patch('llmwikify.cli.commands.serve.MCPAdapter'):
            with patch('asyncio.run'):
                stdout = StringIO()
                with patch('sys.stdout', stdout):
                    args = Args()
                    args.name = 'log-test-wiki'
                    args.transport = None
                    args.host = None
                    args.port = None
                    args.mcp_port = None
                    args.web = False
                    args.auth_token = None
                    args.multi_wiki = False

                    cli.serve(args)

                output = stdout.getvalue()
                assert 'log-test-wiki' in output, (
                    f"Service name should appear in startup log. "
                    f"Output: {output}"
                )
                assert "Starting MCP server 'log-test-wiki'" in output, (
                    f"Startup banner should include service name. "
                    f"Output: {output}"
                )

    def test_cli_overrides_config_name(self, cli):
        """4.4: CLI --name wins over config mcp.name.

        Phase 3 #6 — see test_name_passed_to_serve_mcp.
        """
        cli.config['mcp']['name'] = 'config-wiki'
        with patch('llmwikify.cli.commands.serve.MCPAdapter') as MockAdapter:
            mock_instance = MagicMock()
            MockAdapter.return_value = mock_instance

            with patch('asyncio.run'):
                args = Args()
                args.name = 'cli-wiki'
                args.transport = None
                args.host = None
                args.port = None
                args.mcp_port = None
                args.web = False
                args.auth_token = None
                args.multi_wiki = False

                cli.serve(args)

                call_kwargs = MockAdapter.call_args.kwargs
                assert call_kwargs.get('name') == 'cli-wiki', (
                    f"CLI --name should override config mcp.name. "
                    f"Got: {call_kwargs}"
                )


# ============================================================
# TestConfigFileIntegration — 5.1 to 5.3
# ============================================================
class TestConfigFileIntegration:
    """Test config file integration with mcp.name."""

    def test_config_file_name_is_used(self, temp_wiki):
        """5.1: .wiki-config.yaml mcp.name should be used."""
        config_content = "mcp:\n  name: config-wiki\n  transport: stdio\n"
        (temp_wiki / '.wiki-config.yaml').write_text(config_content)

        import yaml
        config = yaml.safe_load((temp_wiki / '.wiki-config.yaml').read_text()) or {}
        cli = WikiCLI(temp_wiki, config=config)
        cli.wiki.init()

        assert cli.config.get('mcp', {}).get('name') == 'config-wiki'

    def test_no_config_name_uses_directory(self, temp_wiki):
        """5.2: Without mcp.name in config, CLI should fall back to directory name."""
        cli = WikiCLI(temp_wiki, config={'mcp': {'transport': 'stdio'}})
        cli.wiki.init()

        config_name = cli.config.get('mcp', {}).get('name')
        assert config_name is None

    def test_cli_wins_over_config_name(self, temp_wiki):
        """5.3: CLI --name should override config mcp.name.

        Phase 3 #6 — see test_name_passed_to_serve_mcp.
        """
        config_content = "mcp:\n  name: config-wiki\n"
        (temp_wiki / '.wiki-config.yaml').write_text(config_content)

        import yaml
        config = yaml.safe_load((temp_wiki / '.wiki-config.yaml').read_text()) or {}
        cli = WikiCLI(temp_wiki, config=config)
        cli.wiki.init()

        with patch('llmwikify.cli.commands.serve.MCPAdapter') as MockAdapter:
            mock_instance = MagicMock()
            MockAdapter.return_value = mock_instance

            with patch('asyncio.run'):
                args = Args()
                args.name = 'cli-wiki'
                args.transport = None
                args.host = None
                args.port = None
                args.mcp_port = None
                args.web = False
                args.auth_token = None
                args.multi_wiki = False

                cli.serve(args)

                call_kwargs = MockAdapter.call_args.kwargs
                assert call_kwargs.get('name') == 'cli-wiki', (
                    f"CLI --name should override config mcp.name. "
                    f"Got: {call_kwargs}"
                )


# ============================================================
# TestEdgeCases — 6.1 to 6.6
# ============================================================
class TestEdgeCases:
    """Test edge cases for service name."""

    def test_special_chars_directory_name(self):
        """6.1: Directory with special chars should work."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / 'my-wiki_2024'
            tmp_path.mkdir()
            (tmp_path / 'raw').mkdir()
            (tmp_path / 'wiki').mkdir()

            wiki = Wiki(tmp_path)
            wiki.init()

            mcp = create_mcp_server(wiki)
            assert mcp.name == 'my-wiki_2024'
            wiki.close()

    def test_space_directory_name(self):
        """6.2: Directory with spaces should work."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / 'my wiki'
            tmp_path.mkdir()
            (tmp_path / 'raw').mkdir()
            (tmp_path / 'wiki').mkdir()

            wiki = Wiki(tmp_path)
            wiki.init()

            mcp = create_mcp_server(wiki)
            assert mcp.name == 'my wiki'
            wiki.close()

    def test_very_long_directory_name(self):
        """6.3: Very long directory name should not error."""
        long_name = 'a' * 150
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / long_name
            tmp_path.mkdir()
            (tmp_path / 'raw').mkdir()
            (tmp_path / 'wiki').mkdir()

            wiki = Wiki(tmp_path)
            wiki.init()

            mcp = create_mcp_server(wiki)
            assert mcp.name == long_name
            wiki.close()

    def test_unicode_directory_name(self):
        """6.4: Unicode directory name should work."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / '中文wiki'
            tmp_path.mkdir()
            (tmp_path / 'raw').mkdir()
            (tmp_path / 'wiki').mkdir()

            wiki = Wiki(tmp_path)
            wiki.init()

            mcp = create_mcp_server(wiki)
            assert mcp.name == '中文wiki'
            wiki.close()

    def test_config_name_none_falls_back_to_directory(self, tmp_path):
        """6.5: config['name']=None should fall back to directory name."""
        (tmp_path / 'raw').mkdir()
        (tmp_path / 'wiki').mkdir()

        wiki = Wiki(tmp_path)
        wiki.init()

        mcp = create_mcp_server(wiki, config={'name': None})
        assert mcp.name == tmp_path.name
        wiki.close()

    def test_config_name_empty_falls_back_to_directory(self, tmp_path):
        """6.6: config['name']='' should fall back to directory name."""
        (tmp_path / 'raw').mkdir()
        (tmp_path / 'wiki').mkdir()

        wiki = Wiki(tmp_path)
        wiki.init()

        mcp = create_mcp_server(wiki, config={'name': ''})
        assert mcp.name == tmp_path.name
        wiki.close()


# ============================================================
# TestFastMCPIntegration — 7.1 to 7.3
# ============================================================
class TestFastMCPIntegration:
    """Test FastMCP integration with service name."""

    @pytest.fixture
    def wiki(self, tmp_path):
        w = Wiki(tmp_path)
        w.init()
        yield w
        w.close()

    def test_mcp_name_attribute(self, wiki, tmp_path):
        """7.1: MCP instance .name should match expected."""
        mcp = create_mcp_server(wiki, name='test-attr')
        assert mcp.name == 'test-attr'

    def test_mcp_tools_registered(self, wiki):
        """7.2: MCP should have wiki_init tool registered."""
        import asyncio
        mcp = create_mcp_server(wiki, name='tools-test')

        async def check_tools():
            tools = await mcp.list_tools()
            tool_names = [t.name for t in tools]
            return tool_names

        tool_names = _run_async(check_tools())
        assert 'wiki_init' in tool_names
        assert 'wiki_ingest' in tool_names
        assert 'wiki_write_page' in tool_names

    def test_different_names_different_instances(self, wiki, tmp_path):
        """7.3: Two instances with different names should be independent."""
        mcp1 = create_mcp_server(wiki, name='instance-1')
        mcp2 = create_mcp_server(wiki, name='instance-2')

        assert mcp1.name == 'instance-1'
        assert mcp2.name == 'instance-2'
        assert mcp1.name != mcp2.name


# ============================================================
# TestAutoRegisterMcporter — 8.1 to 8.5
# ============================================================
@pytest.mark.skip(reason="_auto_register_mcporter removed from codebase")
class TestAutoRegisterMcporter:
    """Test _auto_register_mcporter() writes to ~/.mcporter/mcporter.json."""

    def test_registers_new_service(self, tmp_path, monkeypatch):
        """8.1: Should write new service to ~/.mcporter/mcporter.json."""
        import json

        from llmwikify.interfaces.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        _auto_register_mcporter("testwiki", "127.0.0.1", 9999)

        config_file = fake_home / ".mcporter" / "mcporter.json"
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert "testwiki" in config["mcpServers"]
        assert config["mcpServers"]["testwiki"]["url"] == "http://127.0.0.1:9999/mcp"
        assert config["mcpServers"]["testwiki"]["type"] == "remote"

    def test_skips_existing_service(self, tmp_path, monkeypatch):
        """8.2: Should skip if service name already registered."""
        import json

        from llmwikify.interfaces.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Pre-populate config
        config_dir = fake_home / ".mcporter"
        config_dir.mkdir()
        config_file = config_dir / "mcporter.json"
        config_file.write_text(json.dumps({
            "mcpServers": {
                "testwiki": {"type": "remote", "url": "http://127.0.0.1:8888/mcp"}
            }
        }))

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            _auto_register_mcporter("testwiki", "127.0.0.1", 9999)

        output = stdout.getvalue()
        assert "already registered" in output.lower() or "skipping" in output.lower()

        # Config should be unchanged
        config = json.loads(config_file.read_text())
        assert config["mcpServers"]["testwiki"]["url"] == "http://127.0.0.1:8888/mcp"

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        """8.3: Should create ~/.mcporter/ if it doesn't exist."""
        from llmwikify.interfaces.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        _auto_register_mcporter("newwiki", "127.0.0.1", 7777)

        config_dir = fake_home / ".mcporter"
        assert config_dir.exists()
        assert (config_dir / "mcporter.json").exists()

    def test_prints_success_message(self, tmp_path, monkeypatch):
        """8.4: Should print success message with URL."""
        from llmwikify.interfaces.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            _auto_register_mcporter("mywiki", "127.0.0.1", 8765)

        output = stdout.getvalue()
        assert "mywiki" in output
        assert "8765" in output
        assert "Registered" in output or "registered" in output

    def test_handles_write_error_gracefully(self, tmp_path, monkeypatch):
        """8.5: Should not crash on write errors."""
        from llmwikify.interfaces.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Make the config dir read-only to trigger an error
        config_dir = fake_home / ".mcporter"
        config_dir.mkdir()
        config_dir.chmod(0o000)

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            try:
                _auto_register_mcporter("failwiki", "127.0.0.1", 5555)
            except Exception:
                pass  # Should not raise

        config_dir.chmod(0o755)  # Restore permissions for cleanup
        output = stdout.getvalue()
        assert "failed" in output.lower() or "error" in output.lower() or "⚠" in output
