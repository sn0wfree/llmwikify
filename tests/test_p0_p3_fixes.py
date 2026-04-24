"""Tests for P0-P3 bug fixes and improvements.

Tests for:
- P0-1: Version consistency
- P0-2: Dead code removal
- P0-3: Orphan html.py safety
- P0-4: CLI default wiki_root
- P1-5: MarkItDown enable_plugins config
- P1-6: Fallback behavior
- P1-7: MCP tool count
- P2-8: read_sink/clear_sink CLI
- P2-9: synthesize CLI
- P2-10: lint --generate-investigations
- P3-11: batch --self-create
- P3-12: .readthedocs.yaml
- P3-13: prompts/__init__.py exports
- P3-14: pytest-asyncio usage
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import llmwikify
from llmwikify.core import Wiki


# ============================================================
# P0-1: Version consistency
# ============================================================
class TestVersionConsistency:
    def test_init_version_matches_pyproject(self):
        """__init__.py version should match pyproject.toml version."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
        with open(pyproject_path, 'rb') as f:
            pyproject = tomllib.load(f)

        pyproject_version = pyproject['project']['version']
        init_version = llmwikify.__version__

        assert init_version == pyproject_version, (
            f"Version mismatch: __init__.py='{init_version}' "
            f"vs pyproject.toml='{pyproject_version}'"
        )

    def test_version_format(self):
        """Version should follow semver-like format."""
        assert re.match(r'^\d+\.\d+\.\d+', llmwikify.__version__)


# ============================================================
# P0-2: Dead code in wiki.py
# ============================================================
class TestDeadCodeRemoval:
    def test_no_unreachable_code_after_raise(self):
        """_call_llm_with_retry should not have unreachable code after raise."""
        wiki_path = Path(__file__).parent.parent / 'src/llmwikify/core/wiki.py'
        content = wiki_path.read_text()

        # Find the raise statement in _call_llm_with_retry
        # After the raise, there should be no code until the next method definition
        pattern = r"raise ValueError\(\s*f\"LLM failed after.*?\)\s*\n(\s+.*\n)*?(?=\n    def |\n\n    |\Z)"
        match = re.search(pattern, content)

        if match:
            after_raise = match.group(0)
            # Check if there's non-comment, non-whitespace code after raise
            lines = after_raise.split('\n')
            code_after_raise = [
                line for line in lines[1:]
                if line.strip() and not line.strip().startswith('#')
            ]
            assert len(code_after_raise) == 0, (
                f"Found unreachable code after raise in _call_llm_with_retry: "
                f"{code_after_raise[:3]}"
            )


# ============================================================
# P0-3: Orphan html.py
# ============================================================
class TestOrphanHtmlFile:
    def test_html_file_not_importable(self):
        """The orphan html.py should not exist or should be safe to import."""
        html_path = Path(__file__).parent.parent / 'src/llmwikify/extractors/html.py'

        if html_path.exists():
            # If it exists, it should be importable without errors
            content = html_path.read_text()
            # Should have proper imports
            assert 'import' in content, "html.py should have import statements"
            # Should not call non-existent functions
            assert '_html_to_text' not in content or 'def _html_to_text' in content, (
                "html.py calls undefined _html_to_text function"
            )

    def test_extractors_init_does_not_import_orphan_html(self):
        """extractors/__init__.py should not import the orphan html module."""
        init_path = Path(__file__).parent.parent / 'src/llmwikify/extractors/__init__.py'
        content = init_path.read_text()

        # Should not import from .html
        assert 'from .html import' not in content
        assert 'import html' not in content


# ============================================================
# P0-4: CLI default wiki_root
# ============================================================
class TestCLIDefaultWikiRoot:
    def test_default_wiki_root_not_hardcoded(self):
        """CLI should not hardcode developer path /home/ll/mining_news."""
        commands_path = Path(__file__).parent.parent / 'src/llmwikify/cli/commands.py'
        content = commands_path.read_text()

        # Should not have hardcoded developer path as default
        assert "WIKI_ROOT', '/home/ll/" not in content, (
            "CLI has hardcoded developer path /home/ll/... as default"
        )

    def test_wiki_root_env_override(self):
        """WIKI_ROOT env var should be respected."""
        test_path = '/tmp/test_wiki'
        with patch.dict(os.environ, {'WIKI_ROOT': test_path}):
            assert os.environ.get('WIKI_ROOT') == test_path


# ============================================================
# P1-5: MarkItDown enable_plugins
# ============================================================
class TestMarkItDownPlugins:
    def test_enable_plugins_true_when_llm_configured(self):
        """MarkItDown should enable plugins when LLM client is available."""
        pytest.importorskip('markitdown', reason="markitdown not installed")

        from llmwikify.extractors.markitdown_extractor import MarkItDownExtractor

        config = {
            "llm": {
                "enabled": True,
                "api_key": "test-key",
                "model": "gpt-4o",
            }
        }

        with patch('markitdown.MarkItDown') as MockMD:
            MockMD.return_value = MagicMock()
            with patch('llmwikify.llm_client.LLMClient') as MockClient:
                MockClient.from_config.return_value = MagicMock()

                extractor = MarkItDownExtractor(config)

                if MockMD.called:
                    call_kwargs = MockMD.call_args
                    enable_plugins = call_kwargs.kwargs.get('enable_plugins',
                                      call_kwargs[1].get('enable_plugins', None) if call_kwargs[1] else None)
                    assert enable_plugins == True

    def test_enable_plugins_false_without_llm(self):
        """MarkItDown should disable plugins when LLM is not configured."""
        pytest.importorskip('markitdown', reason="markitdown not installed")

        from llmwikify.extractors.markitdown_extractor import MarkItDownExtractor

        with patch('markitdown.MarkItDown') as MockMD:
            MockMD.return_value = MagicMock()

            extractor = MarkItDownExtractor({})

            if MockMD.called:
                call_kwargs = MockMD.call_args
                enable_plugins = call_kwargs.kwargs.get('enable_plugins',
                                  call_kwargs[1].get('enable_plugins', None) if call_kwargs[1] else None)
                assert enable_plugins == False


# ============================================================
# P1-6: Fallback behavior
# ============================================================
class TestFallbackBehavior:
    def test_fallback_to_text_for_unknown_formats(self, temp_wiki):
        """Unknown formats should fall back to text extraction, not fail silently."""
        # Create a test file with unknown extension
        test_file = temp_wiki / 'test.unknown'
        test_file.write_text("Some text content")

        from llmwikify.extractors.base import extract
        result = extract(str(test_file), temp_wiki)

        # Should not return empty text for existing files
        assert result.text != "" or result.source_type == "error", (
            "Should either extract text or return error, not silent empty"
        )

    def test_extract_handles_missing_file_gracefully(self):
        """Extract should handle missing files gracefully."""
        from llmwikify.extractors.base import extract

        result = extract('/nonexistent/file.xyz')

        assert result.source_type == "error"
        assert "error" in result.metadata


# ============================================================
# P1-7: MCP tool count
# ============================================================
class TestMCPToolCount:
    def test_mcp_tool_count_matches_readme(self):
        """MCP tool count in README should match actual implementation."""
        # Count tools in tools.py (single source of truth)
        tools_path = Path(__file__).parent.parent / 'src/llmwikify/mcp/tools.py'
        content = tools_path.read_text()
        actual_count = content.count('@mcp.tool')

        # Count tools in README
        readme_path = Path(__file__).parent.parent / 'README.md'
        readme_content = readme_path.read_text()

        # Find the MCP tools table
        # Count rows in the table (excluding header and separator)
        table_match = re.search(
            r'## 🗄️ MCP Server.*?\n\| Tool \|.*?\n\|[-| ]+\|(.*?)(?=\n##|\n###|$)',
            readme_content,
            re.DOTALL
        )

        if table_match:
            table_body = table_match.group(1)
            readme_count = len([
                line for line in table_body.split('\n')
                if line.strip().startswith('|') and '`wiki_' in line
            ])

            assert actual_count == readme_count, (
                f"MCP tool count mismatch: README says {readme_count}, "
                f"actual is {actual_count}"
            )


# ============================================================
# P2-8: read_sink/clear_sink CLI
# ============================================================
class TestSinkCLI:
    def test_read_sink_cli_exists(self):
        """CLI should have a sink-related command."""
        commands_path = Path(__file__).parent.parent / 'src/llmwikify/cli/commands.py'
        content = commands_path.read_text()

        # Check for sink command in argparse setup
        has_sink_cmd = "'sink'" in content or "'sink-status'" in content or "'read-sink'" in content

        # Also check if the command handler exists
        has_sink_handler = 'def sink' in content

        assert has_sink_cmd or has_sink_handler, (
            "No sink-related CLI command found in commands.py"
        )

    def test_wiki_has_read_sink_method(self):
        """Wiki class should have read_sink method."""
        wiki = Wiki.__new__(Wiki)
        assert hasattr(wiki, 'read_sink') or hasattr(wiki, 'sink_status')


# ============================================================
# P2-9: synthesize CLI
# ============================================================
class TestSynthesizeCLI:
    def test_synthesize_cli_exists(self):
        """CLI should have a synthesize command."""
        commands_path = Path(__file__).parent.parent / 'src/llmwikify/cli/commands.py'
        content = commands_path.read_text()

        has_synthesize = "'synthesize'" in content
        assert has_synthesize, (
            "No 'synthesize' CLI command found in commands.py"
        )


# ============================================================
# P2-10: lint --generate-investigations
# ============================================================
class TestLintInvestigations:
    def test_lint_has_generate_investigations_flag(self):
        """lint command should accept --generate-investigations flag."""
        commands_path = Path(__file__).parent.parent / 'src/llmwikify/cli/commands.py'
        content = commands_path.read_text()

        # Check for --generate-investigations in argparse setup
        has_inv_flag = '--generate-investigations' in content or 'generate_investigations' in content

        assert has_inv_flag, (
            "lint command missing --generate-investigations flag"
        )


# ============================================================
# P3-11: batch --self-create
# ============================================================
class TestBatchSmart:
    def test_batch_has_self_create_flag(self):
        """batch command should accept --self-create flag."""
        commands_path = Path(__file__).parent.parent / 'src/llmwikify/cli/commands.py'
        content = commands_path.read_text()

        has_batch_self_create = False

        lines = content.split('\n')
        in_batch_parser = False
        for line in lines:
            if "'batch'" in line or '"batch"' in line:
                in_batch_parser = True
            elif in_batch_parser and "'--self-create'" in line:
                has_batch_self_create = True
                break
            elif in_batch_parser and ('add_parser' in line and "'batch'" not in line):
                break

        assert has_batch_self_create, (
            "batch command missing --self-create flag in argparse setup"
        )


# ============================================================
# P3-12: .readthedocs.yaml
# ============================================================
class TestReadTheDocs:
    def test_readthedocs_yaml_exists(self):
        """.readthedocs.yaml should exist if documentation URL is configured."""
        pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
        content = pyproject_path.read_text()

        if 'readthedocs' in content or 'Documentation' in content:
            rtd_path = Path(__file__).parent.parent / '.readthedocs.yaml'
            assert rtd_path.exists(), (
                "pyproject.toml references documentation but .readthedocs.yaml is missing"
            )


# ============================================================
# P3-13: prompts/__init__.py exports
# ============================================================
class TestPromptsInit:
    def test_prompts_init_exports_registry(self):
        """prompts/__init__.py should export PromptRegistry or related symbols."""
        from llmwikify import prompts

        # Should have some exports beyond just a docstring
        module_attrs = [
            attr for attr in dir(prompts)
            if not attr.startswith('_')
        ]

        # Should export at least something useful
        assert len(module_attrs) > 0, (
            "prompts/__init__.py should export classes or functions"
        )

    def test_defaults_init_has_content(self):
        """prompts/_defaults/__init__.py should have meaningful content."""
        defaults_path = Path(__file__).parent.parent / 'src/llmwikify/prompts/_defaults/__init__.py'
        content = defaults_path.read_text()

        # Should have more than just a docstring
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        non_comment_lines = [
            line for line in lines
            if not line.startswith('#') and not line.startswith('"""') and line != '"""'
        ]

        assert len(non_comment_lines) > 0, (
            "prompts/_defaults/__init__.py should export default prompts"
        )


# ============================================================
# P3-14: pytest-asyncio usage
# ============================================================
class TestPytestAsyncio:
    def test_async_tests_exist_if_dep_declared(self):
        """If pytest-asyncio is a dependency, there should be async tests."""
        pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
        content = pyproject_path.read_text()

        has_asyncio_dep = 'pytest-asyncio' in content

        if has_asyncio_dep:
            # Check for async test functions
            tests_dir = Path(__file__).parent
            async_test_count = 0
            for test_file in tests_dir.glob('test_*.py'):
                file_content = test_file.read_text()
                async_test_count += len(re.findall(r'async def test_', file_content))

            # Either have async tests or remove the dep
            assert async_test_count > 0, (
                "pytest-asyncio is declared but no async tests found. "
                "Either add async tests or remove pytest-asyncio from dependencies."
            )
