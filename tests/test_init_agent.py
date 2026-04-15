"""Tests for init --agent feature — MCP config generation (AGENTS.md removed in v0.26.0)."""

import json

import pytest

from llmwikify.core import Wiki


@pytest.fixture
def temp_wiki(tmp_path):
    return tmp_path


class TestInitAgentOpenCode:
    """Test init with --agent opencode."""

    def test_no_agent_md_created(self, temp_wiki):
        """AGENTS.md is no longer created (wiki.md is single source of truth)."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        assert not (temp_wiki / 'AGENTS.md').exists()
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

    def test_wiki_md_references_raw(self, temp_wiki):
        """wiki.md references raw/ directory."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'raw' / 'gold').mkdir()
        (temp_wiki / 'raw' / 'gold' / 'article.md').write_text("# Test\nContent")
        (temp_wiki / 'raw' / 'copper').mkdir()
        (temp_wiki / 'raw' / 'copper' / 'news.md').write_text("# News\nMore")

        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        content = (temp_wiki / 'wiki.md').read_text()
        assert '`raw/` directory' in content or 'raw/' in content
        wiki.close()

    def test_creates_skill_files(self, temp_wiki):
        """Skill files created for CLI fallback mode."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        skill_md = temp_wiki / '.agents' / 'skills' / 'llmwikify' / 'SKILL.md'
        cli_ref = temp_wiki / '.agents' / 'skills' / 'llmwikify' / 'resources' / 'cli-reference.md'

        assert skill_md.exists()
        assert cli_ref.exists()

        skill_content = skill_md.read_text()
        assert 'llmwikify' in skill_content
        assert 'ingest' in skill_content
        assert 'search' in skill_content
        assert 'cli-reference.md' in skill_content

        cli_content = cli_ref.read_text()
        assert 'init' in cli_content
        assert 'ingest' in cli_content
        assert 'search' in cli_content
        assert 'lint' in cli_content
        wiki.close()

    def test_skill_files_idempotent(self, temp_wiki):
        """Skill files not overwritten on re-init."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        skill_md = temp_wiki / '.agents' / 'skills' / 'llmwikify' / 'SKILL.md'
        original = skill_md.read_text()

        wiki2 = Wiki(temp_wiki)
        result = wiki2.init(agent='opencode')

        assert 'SKILL.md' not in result.get('created_files', [])
        assert skill_md.read_text() == original
        wiki2.close()

    def test_opencode_json_has_instructions(self, temp_wiki):
        """opencode.json includes instructions field for skill auto-load."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        import json
        config = json.loads((temp_wiki / 'opencode.json').read_text())
        assert 'instructions' in config
        assert '.agents/skills/llmwikify/SKILL.md' in config['instructions']
        wiki.close()

    def test_wiki_md_has_kb_management(self, temp_wiki):
        """wiki.md includes Knowledge Base Management and page type conventions."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='opencode')

        content = (temp_wiki / 'wiki.md').read_text()
        assert '## Best Practices' in content
        assert '## Page Types' in content
        wiki.close()


class TestInitAgentClaude:
    """Test init with --agent claude."""

    def test_no_claude_md_created(self, temp_wiki):
        """CLAUDE.md is no longer created (wiki.md is single source of truth)."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='claude')

        assert not (temp_wiki / 'CLAUDE.md').exists()
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

    def test_no_agents_md_created(self, temp_wiki):
        """AGENTS.md is no longer created for codex."""
        wiki = Wiki(temp_wiki)
        wiki.init(agent='codex')

        assert not (temp_wiki / 'AGENTS.md').exists()
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

    def test_skip_existing_mcp_config(self, temp_wiki):
        """MCP config skipped when already exists."""
        (temp_wiki / 'opencode.json').write_text('{"old": true}')
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode')

        assert 'opencode.json' in result['skipped_files']
        wiki.close()

    def test_force_overwrite_mcp_config(self, temp_wiki):
        """MCP config overwritten with --force."""
        (temp_wiki / 'opencode.json').write_text('{"old": true}')
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent='opencode', force=True)

        config = json.loads((temp_wiki / 'opencode.json').read_text())
        assert 'mcp' in config
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
    """Test adding MCP config to an already-initialized wiki."""

    def test_adds_mcp_to_existing_wiki(self, temp_wiki):
        """MCP config can be added to existing wiki."""
        wiki = Wiki(temp_wiki)
        wiki.init()  # Basic init first
        wiki.close()

        wiki2 = Wiki(temp_wiki)
        result = wiki2.init(agent='opencode')

        assert result['status'] in ('already_exists', 'mcp_config_added')
        assert (temp_wiki / 'opencode.json').exists()
        # AGENTS.md should not exist
        assert not (temp_wiki / 'AGENTS.md').exists()
        wiki2.close()


class TestWikiMdMerge:
    """Test --merge flag for wiki.md schema updates."""

    def test_merge_adds_new_sections(self, temp_wiki):
        """New sections from schema are appended to existing wiki.md."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'wiki').mkdir()
        old_schema = (
            "# Wiki Schema\n\n"
            "## Directory Structure\n\n"
            "```\nroot/\n├── raw/\n└── wiki/\n```\n\n"
            "## Conventions\n\n"
            "Use wikilinks.\n\n"
            "## Workflows\n\n"
            "Ingest sources.\n\n"
            "## Best Practices\n\n"
            "1. Be nice\n"
        )
        (temp_wiki / 'wiki.md').write_text(old_schema)

        wiki = Wiki(temp_wiki)
        result = wiki.init(merge=True)

        assert 'wiki.md (merged)' in result['created_files']
        updated = (temp_wiki / 'wiki.md').read_text()
        assert '## Knowledge Graph' in updated
        assert '## Directory Structure' in updated
        assert '## Conventions' in updated
        assert '## Best Practices' in updated
        wiki.close()

    def test_merge_preserves_existing_sections(self, temp_wiki):
        """User-customized sections are not overwritten."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'wiki').mkdir()
        custom_content = (
            "# Wiki Schema\n\n"
            "## My Custom Section\n\n"
            "This is custom content that must be preserved.\n\n"
            "## Best Practices\n\n"
            "1. Be nice\n"
        )
        (temp_wiki / 'wiki.md').write_text(custom_content)

        wiki = Wiki(temp_wiki)
        result = wiki.init(merge=True)

        updated = (temp_wiki / 'wiki.md').read_text()
        assert 'My Custom Section' in updated
        assert 'This is custom content that must be preserved.' in updated
        wiki.close()

    def test_merge_no_new_sections_returns_uptodate(self, temp_wiki):
        """When all sections already exist, returns up-to-date."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki2 = Wiki(temp_wiki)
        result = wiki2.init(merge=True)

        assert 'wiki.md (merged)' in result.get('created_files', []) or \
               'wiki.md (up-to-date)' in result.get('skipped_files', [])
        wiki2.close()

    def test_merge_inserts_before_best_practices(self, temp_wiki):
        """New sections inserted before ## Best Practices."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'wiki').mkdir()
        custom_content = (
            "# Wiki Schema\n\n"
            "## Workflows\n\n"
            "Do things.\n\n"
            "## Best Practices\n\n"
            "1. Be nice\n"
        )
        (temp_wiki / 'wiki.md').write_text(custom_content)

        wiki = Wiki(temp_wiki)
        wiki.init(merge=True)

        updated = (temp_wiki / 'wiki.md').read_text()
        bp_pos = updated.find('## Best Practices')
        new_sections_pos = updated.find('## Schema Updates')
        assert new_sections_pos != -1
        assert new_sections_pos < bp_pos
        wiki.close()

    def test_merge_updates_version(self, temp_wiki):
        """Version number updated even when no new sections."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki2 = Wiki(temp_wiki)
        wiki2.init(merge=True)

        updated = (temp_wiki / 'wiki.md').read_text()
        assert 'Generated by llmwikify v' in updated
        wiki2.close()

    def test_merge_preserves_domain_specific_content(self, temp_wiki):
        """Domain-specific custom content (e.g., mining templates) preserved."""
        (temp_wiki / 'raw').mkdir()
        (temp_wiki / 'wiki').mkdir()
        custom_content = (
            "# Wiki Schema — Mining News\n\n"
            "## Mining Specific Workflows\n\n"
            "Mining-specific content here.\n\n"
            "### Daily News Summary\n\n"
            "Mining daily summary template.\n\n"
            "## Best Practices\n\n"
            "1. Cite sources\n"
        )
        (temp_wiki / 'wiki.md').write_text(custom_content)

        wiki = Wiki(temp_wiki)
        wiki.init(merge=True)

        updated = (temp_wiki / 'wiki.md').read_text()
        assert 'Mining Specific Workflows' in updated
        assert 'Daily News Summary' in updated
        assert 'Mining daily summary template.' in updated
        assert '## Knowledge Graph' in updated
        wiki.close()

    def test_parse_sections_basic(self):
        """_parse_sections correctly extracts H2 sections."""
        content = (
            "# Title\n\n"
            "## Section One\n\n"
            "Content one.\n\n"
            "## Section Two\n\n"
            "Content two.\n"
        )
        sections = Wiki._parse_sections(content)

        assert len(sections) == 2
        assert sections[0] == ('Section One', 'Content one.')
        assert sections[1] == ('Section Two', 'Content two.')

    def test_parse_sections_ignores_h3(self):
        """_parse_sections ignores H3 and deeper headers."""
        content = (
            "## Main Section\n\n"
            "### Sub Section\n\n"
            "Sub content.\n\n"
            "More main content.\n"
        )
        sections = Wiki._parse_sections(content)

        assert len(sections) == 1
        assert sections[0][0] == 'Main Section'
        assert '### Sub Section' in sections[0][1]

    def test_find_insertion_point_best_practices(self):
        """Insertion point found before ## Best Practices."""
        content = (
            "## Workflows\n\n"
            "Do things.\n\n"
            "## Best Practices\n\n"
            "Be nice.\n\n"
            "## Configuration\n\n"
            "Config stuff.\n"
        )
        pos = Wiki._find_insertion_point(content)

        assert content[pos:].startswith('## Best Practices')

    def test_find_insertion_point_configuration(self):
        """Insertion point falls back to ## Configuration."""
        content = (
            "## Workflows\n\n"
            "Do things.\n\n"
            "## Configuration\n\n"
            "Config stuff.\n"
        )
        pos = Wiki._find_insertion_point(content)

        assert content[pos:].startswith('## Configuration')

    def test_find_insertion_point_end_of_file(self):
        """Insertion point defaults to end of file."""
        content = "## Random Section\n\nRandom content.\n"
        pos = Wiki._find_insertion_point(content)

        assert pos == len(content)


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

    def test_analyze_raw_flat_structure(self, temp_wiki):
        """Flat raw/ with files at root level."""
        raw = temp_wiki / 'raw'
        raw.mkdir()
        (raw / 'a.md').write_text("# A")
        (raw / 'b.md').write_text("# B")
        (raw / 'c.txt').write_text("C")

        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 3
        assert stats['categories']['(root)'] == 3
        wiki.close()

    def test_analyze_raw_multi_level_subdir(self, temp_wiki):
        """Multi-level nested subdirectories: raw/gold/2024/Q1/article.md"""
        raw = temp_wiki / 'raw'
        raw.mkdir()
        (raw / 'gold' / '2024' / 'Q1').mkdir(parents=True)
        (raw / 'gold' / '2024' / 'Q1' / 'jan.md').write_text("# Jan")
        (raw / 'gold' / '2024' / 'Q2').mkdir(parents=True)
        (raw / 'gold' / '2024' / 'Q2' / 'may.md').write_text("# May")
        (raw / 'gold' / '2023').mkdir(parents=True)
        (raw / 'gold' / '2023' / 'annual.md').write_text("# Annual")
        (raw / 'copper').mkdir()
        (raw / 'copper' / 'news.md').write_text("# News")

        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 4
        assert stats['categories']['gold'] == 3
        assert stats['categories']['copper'] == 1
        wiki.close()

    def test_analyze_raw_mixed_files_and_dirs(self, temp_wiki):
        """Mixed: root-level files + multi-level subdirectories."""
        raw = temp_wiki / 'raw'
        raw.mkdir()
        (raw / 'root.md').write_text("# Root")
        (raw / 'root2.txt').write_text("Root2")
        (raw / 'gold' / '2024' / 'Q1').mkdir(parents=True)
        (raw / 'gold' / '2024' / 'Q1' / 'a.md').write_text("# A")
        (raw / 'empty_dir').mkdir()

        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 3
        assert stats['categories']['(root)'] == 2
        assert stats['categories']['gold'] == 1
        assert 'empty_dir' not in stats['categories']
        wiki.close()

    def test_analyze_raw_only_empty_subdirs(self, temp_wiki):
        """Only empty subdirectories, no files."""
        raw = temp_wiki / 'raw'
        raw.mkdir()
        (raw / 'gold').mkdir()
        (raw / 'copper' / 'sub').mkdir(parents=True)
        (raw / 'empty').mkdir()

        wiki = Wiki(temp_wiki)
        stats = wiki._analyze_raw()

        assert stats['total'] == 0
        assert stats['categories'] == {}
        wiki.close()
