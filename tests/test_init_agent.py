"""Tests for init --agent feature — agent-specific config generation."""

import pytest
import json
from pathlib import Path

from llmwikify.core import Wiki


@pytest.fixture
def temp_wiki(tmp_path):
    return tmp_path


class TestInitAgentOpenCode:
    """Test init with --agent opencode."""

    def test_creates_agent_md(self, temp_wiki):
        """AGENTS.md created for opencode."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        assert (temp_wiki / 'AGENTS.md').exists()
        content = (temp_wiki / 'AGENTS.md').read_text()
        assert 'Agent Instructions' in content
        assert 'wiki.md' in content
        wiki.close()

    def test_creates_opencode_json(self, temp_wiki):
        """opencode.json created with correct MCP config."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        config_path = temp_wiki / 'opencode.json'
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert config['mcp']['llmwikify']['type'] == 'local'
        assert config['mcp']['llmwikify']['command'] == ['llmwikify', 'mcp']
        wiki.close()

    def test_creates_gitignore(self, temp_wiki):
        """.gitignore created."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        assert (temp_wiki / '.gitignore').exists()
        content = (temp_wiki / '.gitignore').read_text()
        assert '.llmwikify.db' in content
        assert 'wiki/.sink/' in content
        wiki.close()

    def test_raw_analysis_in_agent_md(self, temp_wiki):
        """Agent MD includes raw/ analysis."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'raw' / 'gold').mkdir()
        (temp_wiki / 'raw' / 'gold' / 'article.md').write_text("# Test\nContent")
        (temp_wiki / 'raw' / 'copper').mkdir()
        (temp_wiki / 'raw' / 'copper' / 'news.md').write_text("# News\nMore")

        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        content = (temp_wiki / 'AGENTS.md').read_text()
        assert '2 files' in content
        wiki.close()


class TestInitAgentClaude:
    """Test init with --agent claude."""

    def test_creates_claude_md(self, temp_wiki):
        """CLAUDE.md created for claude."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='claude')

        assert (temp_wiki / 'CLAUDE.md').exists()
        content = (temp_wiki / 'CLAUDE.md').read_text()
        assert 'Instructions' in content
        wiki.close()

    def test_creates_mcp_json(self, temp_wiki):
        """.mcp.json created with Claude format."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='claude')

        config_path = temp_wiki / '.mcp.json'
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert 'mcpServers' in config
        assert config['mcpServers']['llmwikify']['command'] == 'llmwikify'
        assert config['mcpServers']['llmwikify']['args'] == ['mcp']
        wiki.close()


class TestInitAgentCodex:
    """Test init with --agent codex."""

    def test_creates_agents_md(self, temp_wiki):
        """AGENTS.md created for codex."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='codex')

        assert (temp_wiki / 'AGENTS.md').exists()
        wiki.close()

    def test_creates_dot_opencode_json(self, temp_wiki):
        """.opencode.json created."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='codex')

        config_path = temp_wiki / '.opencode.json'
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert 'mcp' in config
        wiki.close()


class TestInitAgentGeneric:
    """Test init with --agent generic (no agent files)."""

    def test_no_agent_files(self, temp_wiki):
        """Generic mode creates wiki.md but no agent/MCP files."""
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='generic')

        assert (temp_wiki / 'wiki.md').exists()
        assert not (temp_wiki / 'AGENTS.md').exists()
        assert not (temp_wiki / 'CLAUDE.md').exists()
        assert not (temp_wiki / 'opencode.json').exists()
        assert not (temp_wiki / '.mcp.json').exists()
        assert '.gitignore' in result['created_files']
        wiki.close()


class TestInitNoAgent:
    """Test init without --agent (backward compat)."""

    def test_basic_init_without_agent(self, temp_wiki):
        """Init without agent param works as before."""
        wiki = Wiki(temp_wiki)
        result = wiki.init()

        assert result['status'] == 'created'
        assert 'wiki.md' in result['created_files']
        assert not (temp_wiki / 'AGENTS.md').exists()
        assert not (temp_wiki / 'opencode.json').exists()
        wiki.close()


class TestInitForceAndSkip:
    """Test force overwrite and skip behavior."""

    def test_skip_existing_wiki_md(self, temp_wiki):
        """wiki.md skipped when already exists."""
        (temp_wiki / 'wiki.md').write_text("# Existing\nCustom content")
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode')

        assert 'wiki.md' in result['skipped_files']
        assert 'Schema file already exists' in result['warnings'][0]
        wiki.close()

    def test_force_overwrite_wiki_md(self, temp_wiki):
        """wiki.md overwritten with --force."""
        (temp_wiki / 'wiki.md').write_text("# Existing\nCustom content")
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode', force=True)

        content = (temp_wiki / 'wiki.md').read_text()
        assert 'Wiki Schema' in content
        assert 'Custom content' not in content
        wiki.close()

    def test_skip_existing_agent_file(self, temp_wiki):
        """Agent file skipped when already exists."""
        (temp_wiki / 'AGENTS.md').write_text("# Custom Agent Config")
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode')

        assert 'AGENTS.md' in result['skipped_files']
        wiki.close()

    def test_force_overwrite_agent_file(self, temp_wiki):
        """Agent file overwritten with --force."""
        (temp_wiki / 'AGENTS.md').write_text("# Custom Agent Config")
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode', force=True)

        content = (temp_wiki / 'AGENTS.md').read_text()
        assert 'Agent Instructions' in content
        assert 'Custom Agent Config' not in content
        wiki.close()

    def test_merge_regenerates_agent_file(self, temp_wiki):
        """Agent file regenerated with --merge."""
        (temp_wiki / 'AGENTS.md').write_text("# Custom Agent Config")
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode', merge=True)

        content = (temp_wiki / 'AGENTS.md').read_text()
        assert 'Agent Instructions' in content
        assert 'Custom Agent Config' not in content
        wiki.close()

    def test_merge_regenerates_mcp_config(self, temp_wiki):
        """MCP config regenerated with --merge."""
        (temp_wiki / 'opencode.json').write_text('{"old": true}')
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode', merge=True)

        config = json.loads((temp_wiki / 'opencode.json').read_text())
        assert 'mcp' in config
        assert 'old' not in config
        wiki.close()


class TestInitAgentOnExistingWiki:
    """Test adding agent config to an already-initialized wiki."""

    def test_adds_agent_to_existing_wiki(self, temp_wiki):
        """Agent config can be added to existing wiki."""
        wiki = Wiki(temp_wiki)
        wiki.init()  # Basic init first
        wiki.close()

        wiki2 = Wiki(temp_wiki)
        result = wiki2.init(agent='opencode')

        assert result['status'] in ('already_exists', 'agent_config_added')
        assert (temp_wiki / 'AGENTS.md').exists()
        assert (temp_wiki / 'opencode.json').exists()
        wiki2.close()


class TestRawAnalysis:
    """Test raw/ directory analysis."""

    def test_empty_raw(self, temp_wiki):
        """Empty raw/ returns zero counts."""
        (temp_wiki / 'raw').mkdir()
        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 0
        assert stats['categories'] == {}
        wiki.close()

    def test_categorizes_by_subdir(self, temp_wiki):
        """Counts files per category subdirectory."""
        raw = temp_wiki / 'raw'
        raw.mkdir()
        (raw / 'gold').mkdir()
        (raw / 'gold' / 'a.md').write_text("# A")
        (raw / 'gold' / 'b.md').write_text("# B")
        (raw / 'copper').mkdir()
        (raw / 'copper' / 'c.md').write_text("# C")

        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 3
        assert stats['categories']['gold'] == 2
        assert stats['categories']['copper'] == 1
        wiki.close()

    def test_no_raw_dir(self, temp_wiki):
        """No raw/ directory returns empty stats."""
        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 0
        assert stats['categories'] == {}
        wiki.close()
