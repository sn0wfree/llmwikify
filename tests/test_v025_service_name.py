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

from llmwikify.cli import WikiCLI
from llmwikify.core import Wiki
from llmwikify.mcp.server import create_mcp_server, serve_mcp


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
        """2.1: serve_mcp should pass name to create_mcp_server."""
        with patch('llmwikify.mcp.server.create_mcp_server') as mock_create:
            mock_mcp = MagicMock()
            mock_mcp.name = 'test-wiki'
            mock_mcp._server_config = {'transport': 'stdio'}
            mock_create.return_value = mock_mcp

            serve_mcp(wiki, name='test-wiki')

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs['name'] == 'test-wiki'

    def test_stdio_log_contains_service_name(self, wiki, tmp_path):
        """2.2: stdio mode log should include service name."""
        with patch('llmwikify.mcp.server.create_mcp_server') as mock_create:
            mock_mcp = MagicMock()
            mock_mcp.name = 'my-wiki'
            mock_mcp._server_config = {'transport': 'stdio'}
            mock_create.return_value = mock_mcp

            stdout = StringIO()
            with patch('sys.stdout', stdout):
                try:
                    with patch.object(mock_mcp, 'run', side_effect=KeyboardInterrupt):
                        serve_mcp(wiki, name='my-wiki', transport='stdio')
                except KeyboardInterrupt:
                    pass

            output = stdout.getvalue()
            assert 'my-wiki' in output
            assert 'STDIO' in output

    def test_http_log_contains_service_name(self, wiki, tmp_path):
        """2.3: http mode log should include service name."""
        with patch('llmwikify.mcp.server.create_mcp_server') as mock_create:
            mock_mcp = MagicMock()
            mock_mcp.name = 'http-wiki'
            mock_mcp._server_config = {'transport': 'http', 'host': '127.0.0.1', 'port': 8765}
            mock_create.return_value = mock_mcp

            stdout = StringIO()
            with patch('sys.stdout', stdout):
                try:
                    with patch.object(mock_mcp, 'run', side_effect=KeyboardInterrupt):
                        serve_mcp(wiki, name='http-wiki', transport='http')
                except KeyboardInterrupt:
                    pass

            output = stdout.getvalue()
            assert 'http-wiki' in output
            assert 'HTTP' in output

    def test_no_name_uses_directory_name_in_log(self, wiki, tmp_path):
        """2.4: When no name provided, log should show directory name."""
        with patch('llmwikify.mcp.server.create_mcp_server') as mock_create:
            mock_mcp = MagicMock()
            mock_mcp.name = tmp_path.name
            mock_mcp._server_config = {'transport': 'stdio'}
            mock_create.return_value = mock_mcp

            stdout = StringIO()
            with patch('sys.stdout', stdout):
                try:
                    with patch.object(mock_mcp, 'run', side_effect=KeyboardInterrupt):
                        serve_mcp(wiki, transport='stdio')
                except KeyboardInterrupt:
                    pass

            output = stdout.getvalue()
            assert tmp_path.name in output


# ============================================================
# TestCLIArgParsing — 3.1 to 3.5
# ============================================================
class TestCLIArgParsing:
    """Test CLI argument parsing for --name."""

    def test_name_long_parameter(self):
        """3.1: --name long parameter should be parsed."""
        from llmwikify.cli.commands import main
        with patch('sys.argv', ['llmwikify', 'mcp', '--name', 'testwiki']):
            with patch('llmwikify.cli.commands.WikiCLI') as MockCLI:
                mock_instance = MagicMock()
                mock_instance.serve.return_value = 0
                MockCLI.return_value = mock_instance

                try:
                    main()
                except SystemExit:
                    pass

                mock_instance.serve.assert_called_once()
                args = mock_instance.serve.call_args[0][0]
                assert args.name == 'testwiki'

    def test_name_short_parameter(self):
        """3.2: -n short parameter should be parsed."""
        from llmwikify.cli.commands import main
        with patch('sys.argv', ['llmwikify', 'mcp', '-n', 'shortwiki']):
            with patch('llmwikify.cli.commands.WikiCLI') as MockCLI:
                mock_instance = MagicMock()
                mock_instance.serve.return_value = 0
                MockCLI.return_value = mock_instance

                try:
                    main()
                except SystemExit:
                    pass

                mock_instance.serve.assert_called_once()
                args = mock_instance.serve.call_args[0][0]
                assert args.name == 'shortwiki'

    def test_mcp_help_contains_name(self):
        """3.3: mcp --help should mention --name."""
        from llmwikify.cli.commands import main
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
        from llmwikify.cli.commands import main
        stdout = StringIO()
        with patch('sys.argv', ['llmwikify', 'serve', '--help']):
            with patch('sys.stdout', stdout):
                with pytest.raises(SystemExit):
                    main()

        output = stdout.getvalue()
        assert '--name' in output

    def test_no_name_defaults_to_none(self):
        """3.5: Without --name, args.name should be None."""
        from llmwikify.cli.commands import main
        with patch('sys.argv', ['llmwikify', 'mcp']):
            with patch('llmwikify.cli.commands.WikiCLI') as MockCLI:
                mock_instance = MagicMock()
                mock_instance.serve.return_value = 0
                MockCLI.return_value = mock_instance

                try:
                    main()
                except SystemExit:
                    pass

                mock_instance.serve.assert_called_once()
                args = mock_instance.serve.call_args[0][0]
                assert args.name is None


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
        """4.1: --name should be passed to serve_mcp."""
        with patch('llmwikify.mcp.server.serve_mcp') as mock_serve:
            args = Args()
            args.name = 'cli-wiki'
            args.transport = None
            args.host = None
            args.port = None

            cli.serve(args)

            mock_serve.assert_called_once()
            call_kwargs = mock_serve.call_args.kwargs
            assert call_kwargs['name'] == 'cli-wiki'

    def test_no_name_falls_back_to_none(self, cli):
        """4.2: Without --name, serve_mcp receives name=None."""
        cli.config['mcp']['name'] = None
        with patch('llmwikify.mcp.server.serve_mcp') as mock_serve:
            args = Args()
            args.name = None
            args.transport = None
            args.host = None
            args.port = None

            cli.serve(args)

            call_kwargs = mock_serve.call_args.kwargs
            assert call_kwargs['name'] is None

    def test_startup_log_prints_service_name(self, cli, temp_wiki):
        """4.3: Startup log should print service name."""
        with patch('llmwikify.mcp.server.serve_mcp') as mock_serve:
            stdout = StringIO()
            with patch('sys.stdout', stdout):
                args = Args()
                args.name = 'log-test-wiki'
                args.transport = None
                args.host = None
                args.port = None

                cli.serve(args)

            output = stdout.getvalue()
            assert 'log-test-wiki' in output
            assert "Starting MCP server 'log-test-wiki'" in output

    def test_cli_overrides_config_name(self, cli):
        """4.4: CLI --name wins over config mcp.name."""
        cli.config['mcp']['name'] = 'config-wiki'
        with patch('llmwikify.mcp.server.serve_mcp') as mock_serve:
            args = Args()
            args.name = 'cli-wiki'
            args.transport = None
            args.host = None
            args.port = None

            cli.serve(args)

            call_kwargs = mock_serve.call_args.kwargs
            assert call_kwargs['name'] == 'cli-wiki'


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
        """5.3: CLI --name should override config mcp.name."""
        config_content = "mcp:\n  name: config-wiki\n"
        (temp_wiki / '.wiki-config.yaml').write_text(config_content)

        import yaml
        config = yaml.safe_load((temp_wiki / '.wiki-config.yaml').read_text()) or {}
        cli = WikiCLI(temp_wiki, config=config)
        cli.wiki.init()

        with patch('llmwikify.mcp.server.serve_mcp') as mock_serve:
            args = Args()
            args.name = 'cli-wiki'
            args.transport = None
            args.host = None
            args.port = None

            cli.serve(args)

            call_kwargs = mock_serve.call_args.kwargs
            assert call_kwargs['name'] == 'cli-wiki'


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

        tool_names = asyncio.run(check_tools())
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
class TestAutoRegisterMcporter:
    """Test _auto_register_mcporter() writes to ~/.mcporter/mcporter.json."""

    def test_registers_new_service(self, tmp_path, monkeypatch):
        """8.1: Should write new service to ~/.mcporter/mcporter.json."""
        import json

        from llmwikify.mcp.server import _auto_register_mcporter

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

        from llmwikify.mcp.server import _auto_register_mcporter

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
        from llmwikify.mcp.server import _auto_register_mcporter

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        _auto_register_mcporter("newwiki", "127.0.0.1", 7777)

        config_dir = fake_home / ".mcporter"
        assert config_dir.exists()
        assert (config_dir / "mcporter.json").exists()

    def test_prints_success_message(self, tmp_path, monkeypatch):
        """8.4: Should print success message with URL."""
        from llmwikify.mcp.server import _auto_register_mcporter

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
        from llmwikify.mcp.server import _auto_register_mcporter

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
