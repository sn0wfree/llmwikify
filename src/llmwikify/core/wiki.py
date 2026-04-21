"""Wiki core business logic."""

import json
import logging
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_db_path, get_directory, load_config
from ..extractors import extract
from .index import WikiIndex
from .query_sink import QuerySink

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
VALID_AGENTS = ("opencode", "claude", "codex", "generic")


class Wiki:
    """Main Wiki manager."""

    def __init__(self, root: Path, config: dict | None = None):
        self.root = root.resolve()

        # Load configuration (external file or built-in defaults)
        self.config = config or load_config(self.root)

        # Set up directory structure from config
        self.raw_dir = get_directory(self.root, 'raw', self.config)
        self.wiki_dir = get_directory(self.root, 'wiki', self.config)

        # Query sink directory (pending updates for query pages)
        self.sink_dir = self.wiki_dir / '.sink'

        # Internal files (hardcoded — not user-configurable)
        self.index_file = self.wiki_dir / 'index.md'
        self.log_file = self.wiki_dir / 'log.md'
        self.wiki_md_file = self.root / 'wiki.md'
        self.db_path = get_db_path(self.root, self.config)

        # Special page names (from filenames, used for exclusion logic)
        self._index_page_name = 'index'
        self._log_page_name = 'log'

        # Reference index path
        ref_index_name = self.config.get('reference_index', {}).get('name', 'reference_index.json')
        self._ref_index_path: Path | None = None
        self._ref_index_name = ref_index_name

        # Orphan detection configuration
        orphan_config = self.config.get('orphan_detection', {})
        self._default_exclude_patterns = orphan_config.get('default_exclude_patterns', [])
        self._user_exclude_patterns = orphan_config.get('exclude_patterns', [])
        self._exclude_frontmatter_keys = orphan_config.get('exclude_frontmatter', [])
        self._archive_dirs = orphan_config.get('archive_directories', [])

        # Performance settings
        perf_config = self.config.get('performance', {})
        self._batch_size = perf_config.get('batch_size', 100)

        self._index: WikiIndex | None = None
        self._query_sink: QuerySink | None = None

        # Prompt custom directory (optional, from config)
        prompts_config = self.config.get("prompts", {})
        custom_dir = prompts_config.get("custom_dir")
        self._prompt_custom_dir: Path | None = None
        if custom_dir:
            self._prompt_custom_dir = (self.root / custom_dir).resolve()

    def _get_prompt_registry(self) -> "PromptRegistry":
        """Create a PromptRegistry instance with current provider and custom dir."""
        from .prompt_registry import PromptRegistry
        provider = self.config.get("llm", {}).get("provider", "openai")
        return PromptRegistry(provider=provider, custom_dir=self._prompt_custom_dir)

    def _get_index_summary(self) -> str:
        """Return a condensed wiki index (max 500 chars)."""
        if not self.index_file.exists():
            return "(no index)"
        content = self.index_file.read_text()
        if len(content) <= 500:
            return content
        return content[:497] + "..."

    def _get_recent_log(self, limit: int = 3) -> str:
        """Return recent log entries."""
        if not self.log_file.exists():
            return "(no log)"
        lines = self.log_file.read_text().strip().split("\n")
        return "\n".join(lines[-limit:])

    def _get_page_count(self) -> int:
        """Return number of wiki pages."""
        if not self.wiki_dir.exists():
            return 0
        return len([p for p in self.wiki_dir.rglob("*.md")
                    if p.stem not in (self._index_page_name, self._log_page_name)
                    and '.sink' not in str(p)])

    def _get_existing_page_names(self) -> list[str]:
        """Return list of existing wiki page names (relative to wiki_dir)."""
        if not self.wiki_dir.exists():
            return []
        return [str(p.relative_to(self.wiki_dir)) for p in self.wiki_dir.rglob("*.md")
                if p.stem not in (self._index_page_name, self._log_page_name)
                and '.sink' not in str(p)]

    def _wiki_pages(self) -> list[Path]:
        """Return all wiki pages recursively, excluding index, log, and .sink/."""
        if not self.wiki_dir.exists():
            return []
        return [p for p in self.wiki_dir.rglob("*.md")
                if p.stem not in (self._index_page_name, self._log_page_name)
                and '.sink' not in str(p)]

    def _page_display_name(self, page: Path) -> str:
        """Return display name for a page (relative path without .md)."""
        return str(page.relative_to(self.wiki_dir))[:-3]  # strip .md

    def _resolve_wikilink_target(self, target: str) -> Path | None:
        """Resolve a wikilink target to a file path.

        Resolution order:
        1. Direct path (e.g., "concepts/Factor Investing")
        2. SQLite index lookup (authoritative, supports all formats)
        """
        # Layer 1: Direct path match (e.g., "concepts/Factor Investing")
        direct = self.wiki_dir / f"{target}.md"
        if direct.exists():
            return direct

        # Layer 2: SQLite index lookup
        try:
            file_path = self.index.resolve_by_name(target)
            if file_path:
                return self.wiki_dir / file_path
        except Exception:
            logger.debug("Index lookup failed for wikilink: %s", target)

        return None

    def fix_wikilinks(self, dry_run: bool = True) -> dict:
        """Scan all wiki pages and fix broken wikilinks by adding directory prefix.

        When a wikilink [[X]] is broken but a page with base name X exists in a
        subdirectory, this method adds the directory prefix to the link.

        Args:
            dry_run: If True, only report what would be changed.

        Returns:
            {"fixed": N, "skipped": M, "ambiguous": K, "changes": [...]}
        """
        changes = []
        stats: dict[str, int] = {"fixed": 0, "skipped": 0, "ambiguous": 0}

        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            new_content = content
            page_modified = False

            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target in (self._index_page_name, self._log_page_name):
                    continue

                # Already has directory prefix or is a root-level page — skip
                if '/' in target:
                    continue
                if (self.wiki_dir / f"{target}.md").exists():
                    continue

                # Find pages matching the base name
                matches = [p for p in self.wiki_dir.rglob(f"{target}.md")]

                if len(matches) == 0:
                    stats["skipped"] += 1
                    continue

                if len(matches) > 1:
                    stats["ambiguous"] += 1
                    changes.append({
                        "page": self._page_display_name(page),
                        "link": target,
                        "status": "ambiguous",
                        "matches": [str(m.relative_to(self.wiki_dir)) for m in matches],
                    })
                    continue

                # Single match: add directory prefix
                rel_path = str(matches[0].relative_to(self.wiki_dir))[:-3]

                # Build replacement wikilink
                if '#' in link:
                    section = link.split('#', 1)[1]
                    if '|' in section:
                        sec, disp = section.split('|', 1)
                        new_wikilink = f"[[{rel_path}#{sec}|{disp}]]"
                    else:
                        new_wikilink = f"[[{rel_path}#{section}]]"
                elif '|' in link:
                    display = link.split('|', 1)[1]
                    new_wikilink = f"[[{rel_path}|{display}]]"
                else:
                    new_wikilink = f"[[{rel_path}]]"

                old_wikilink = f"[[{link}]]"
                new_content = new_content.replace(old_wikilink, new_wikilink, 1)
                page_modified = True
                stats["fixed"] += 1
                changes.append({
                    "page": self._page_display_name(page),
                    "old": old_wikilink,
                    "new": new_wikilink,
                    "status": "fixed",
                })

            if page_modified and not dry_run:
                page.write_text(new_content)
                # Re-index the page
                rel_path = str(page.relative_to(self.wiki_dir))
                self.index.upsert_page(rel_path[:-3], new_content, rel_path)

        return {**stats, "changes": changes}

    @property
    def ref_index_path(self) -> Path:
        """Path to reference index JSON."""
        if self._ref_index_path is None:
            self._ref_index_path = self.wiki_dir / self._ref_index_name
        return self._ref_index_path

    @property
    def index(self) -> WikiIndex:
        """Lazy-load WikiIndex."""
        if self._index is None:
            self._index = WikiIndex(self.db_path)
        return self._index

    @property
    def query_sink(self) -> QuerySink:
        """Lazy-load QuerySink."""
        if self._query_sink is None:
            self._query_sink = QuerySink(self.root, self.wiki_dir)
        return self._query_sink

    def is_initialized(self) -> bool:
        """Check if wiki is initialized."""
        return (self.raw_dir.exists() and
                self.wiki_dir.exists() and
                self.db_path.exists())

    def init(self, overwrite: bool = False, agent: str | None = None,
             force: bool = False, merge: bool = False) -> dict:
        """Initialize wiki directory structure.
        
        Args:
            overwrite: If True, recreate index.md and log.md even if they exist.
                       Always skips wiki.md and config_example if they exist.
            agent: Agent type for MCP config generation. One of: opencode, claude, codex, generic.
                   None = skip MCP config generation. Generic = no MCP config.
            force: If True, overwrite existing files without prompting.
            merge: If True, merge into existing wiki.md instead of skipping.
        
        Returns:
            Structured result with status, created_files, and message.
        """
        already_exists = self.is_initialized()

        if already_exists and not overwrite:
            return self._handle_existing_init(agent, merge, force)

        return self._create_new_init(agent, force, merge, overwrite)

    def _handle_existing_init(self, agent: str | None, merge: bool, force: bool) -> dict:
        """Handle initialization when wiki already exists."""
        created = []
        skipped = []
        warnings = []

        existing = []
        if self.raw_dir.exists():
            existing.append("raw/")
        if self.wiki_dir.exists():
            existing.append("wiki/")
        if self.index_file.exists():
            existing.append("index.md")
        if self.log_file.exists():
            existing.append("log.md")

        if merge:
            merged_content = self._merge_wiki_md()
            original_content = self.wiki_md_file.read_text()
            if merged_content != original_content:
                self.wiki_md_file.write_text(merged_content)
                created.append("wiki.md (merged)")
            else:
                skipped.append("wiki.md (up-to-date)")

        self._generate_mcp_config_if_needed(agent, force, merge, created, skipped, warnings)

        raw_stats = self._analyze_raw()
        status_msg = "already_exists" if not created else "mcp_config_added"
        return {
            "status": status_msg,
            "created_files": created,
            "existing_files": existing,
            "skipped_files": skipped,
            "warnings": warnings,
            "raw_stats": raw_stats,
            "agent": agent,
            "message": f"Wiki already initialized at {self.root}",
        }

    def _create_new_init(self, agent: str | None, force: bool, merge: bool, overwrite: bool = False) -> dict:
        """Handle initialization for new wiki."""
        created = []
        skipped = []
        warnings = []

        self._create_directories(created, skipped)
        self.index.initialize()
        self._create_core_files(created, skipped, overwrite)
        self._handle_wiki_md_schema(created, skipped, warnings, force, merge)
        self._generate_mcp_config_if_needed(agent, force, merge, created, skipped, warnings)
        self._generate_gitignore_if_needed(created)
        self._generate_skill_files_if_needed(created)

        raw_stats = self._analyze_raw()
        return {
            "status": "created",
            "created_files": created,
            "existing_files": [],
            "skipped_files": skipped,
            "warnings": warnings,
            "raw_stats": raw_stats,
            "agent": agent,
            "message": f"Wiki initialized at {self.root}",
        }

    def _create_directories(self, created: list, skipped: list) -> None:
        """Create wiki directory structure."""
        for dir_path, name in [(self.raw_dir, "raw/"), (self.wiki_dir, "wiki/")]:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created.append(name)
            else:
                skipped.append(name)

        for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
            sub_path = self.wiki_dir / subdir
            if not sub_path.exists():
                sub_path.mkdir(parents=True, exist_ok=True)
                created.append(f"wiki/{subdir}/")
            else:
                skipped.append(f"wiki/{subdir}/")

        if not self.sink_dir.exists():
            self.sink_dir.mkdir(parents=True, exist_ok=True)
            created.append("wiki/.sink/")
        else:
            skipped.append("wiki/.sink/")

    def _create_core_files(self, created: list, skipped: list, overwrite: bool = False) -> None:
        """Create index.md, log.md, overview.md, and config example."""
        for file_path, name, generator in [
            (self.index_file, "index.md", self._generate_index_content),
            (self.log_file, "log.md", self._generate_log_content),
            (self.wiki_dir / "overview.md", "overview.md", self._generate_overview_content),
        ]:
            if not file_path.exists() or overwrite:
                file_path.write_text(generator())
                created.append(name)
            else:
                skipped.append(name)

        config_example = self.root / '.wiki-config.yaml.example'
        if not config_example.exists():
            config_example.write_text(self._generate_config_example())
            created.append(".wiki-config.yaml.example")
        else:
            skipped.append(".wiki-config.yaml.example")

    def _handle_wiki_md_schema(self, created: list, skipped: list, warnings: list,
                                force: bool, merge: bool) -> None:
        """Handle wiki.md schema creation, merging, or skipping."""
        legacy_wiki = self.root / 'WIKI.md'
        has_wiki = self.wiki_md_file.exists()
        has_WIKI = legacy_wiki.exists()

        if has_wiki and not force and not merge:
            warnings.append(
                f"Schema file already exists: wiki.md ({self.wiki_md_file.stat().st_size} bytes). "
                "Use --force to overwrite or --merge to merge."
            )
            skipped.append("wiki.md")
        elif merge and has_wiki:
            merged_content = self._merge_wiki_md()
            original_content = self.wiki_md_file.read_text()
            if merged_content != original_content:
                self.wiki_md_file.write_text(merged_content)
                created.append("wiki.md (merged)")
            else:
                skipped.append("wiki.md (up-to-date)")
        elif force and has_wiki:
            self.wiki_md_file.write_text(self._generate_wiki_md())
            created.append("wiki.md")
        elif not has_wiki:
            self.wiki_md_file.write_text(self._generate_wiki_md())
            created.append("wiki.md")

        if has_WIKI and not has_wiki:
            warnings.append(
                "Legacy WIKI.md found. The new schema will be generated as wiki.md (lowercase). "
                "Consider removing or merging WIKI.md."
            )

    def _generate_mcp_config_if_needed(self, agent: str | None, force: bool, merge: bool,
                                        created: list, skipped: list, warnings: list) -> None:
        """Generate MCP config and skill files if agent is specified."""
        if not agent or agent == "generic":
            return

        mcp_filename = ".mcp.json" if agent == "claude" else (
            "opencode.json" if agent == "opencode" else ".opencode.json"
        )
        mcp_path = self.root / mcp_filename
        if not mcp_path.exists() or force or merge:
            content = self._generate_mcp_config(agent)
            if content:
                mcp_path.write_text(content)
                created.append(mcp_filename)
            else:
                skipped.append(mcp_filename)
        else:
            skipped.append(mcp_filename)
            warnings.append(f"{mcp_filename} already exists, skipping.")

        self._generate_skill_files_if_needed(created)

    def _generate_gitignore_if_needed(self, created: list) -> None:
        """Generate .gitignore if it doesn't exist."""
        gitignore_path = self.root / '.gitignore'
        if not gitignore_path.exists():
            content = self._generate_gitignore()
            if content:
                gitignore_path.write_text(content)
                created.append(".gitignore")

    def _generate_skill_files_if_needed(self, created: list) -> None:
        """Generate skill files for CLI fallback if they don't exist."""
        skill_created = self._generate_skill_files()
        created.extend(skill_created)

    def _generate_index_content(self) -> str:
        """Generate initial index.md content."""
        return (
            "# Wiki Index\n\n"
            f"Generated by llmwikify v{self._get_version()}\n\n"
            "---\n\n"
            "## Pages\n\n"
            "*(No pages yet)*\n"
        )

    def _generate_log_content(self) -> str:
        """Generate initial log.md content."""
        return (
            "# Wiki Log\n\n"
            f"Initialized: {self._now()}\n\n"
            "---\n"
        )

    def _generate_overview_content(self) -> str:
        """Generate initial overview.md content."""
        return (
            "---\n"
            "title: Overview\n"
            "type: overview\n"
            f"created: {self._now()[:10]}\n"
            f"updated: {self._now()[:10]}\n"
            "sources: []\n"
            "tags: []\n"
            "---\n\n"
            "# Overview\n\n"
            "> This page is the top-level synthesis of the entire knowledge base.\n"
            "> Revise as sources are ingested and understanding deepens.\n\n"
            "## Scope\n\n"
            "*(Describe the wiki's domain and purpose)*\n\n"
            "## Current State\n\n"
            "*(Summary of current understanding based on ingested sources)*\n\n"
            "## Key Themes\n\n"
            "*(List key themes with [[wikilinks]] to relevant pages)*\n\n"
            "## Working Theses\n\n"
            "*(Working hypotheses or arguments the wiki is building)*\n\n"
            "## Open Questions\n\n"
            "*(Questions that remain unanswered as sources are added)*\n"
        )

    def _generate_config_example(self) -> str:
        """Generate .wiki-config.yaml.example content."""
        return (
            "# Wiki Configuration\n"
            "# See docs/CONFIG_GUIDE.md for details\n\n"
            "# Override default directories\n"
            "# directories:\n"
            "#   raw: raw\n"
            "#   wiki: wiki\n\n"
            "# Override database name\n"
            "# database:\n"
            "#   name: \".llmwikify.db\"\n\n"
            "# Orphan detection exclusions\n"
            "# orphan_detection:\n"
            "#   exclude_patterns:\n"
            "#     - '^\\d{4}-\\d{2}-\\d{2}$'  # Date pages\n"
            "#     - '^meeting-.*'             # Meeting notes\n"
            "#   exclude_frontmatter:\n"
            "#     - redirect_to\n"
            "#   archive_directories:\n"
            "#     - 'archive'\n"
            "#     - 'logs'\n\n"
            "# MCP server settings\n"
            "# mcp:\n"
            "#   host: 127.0.0.1\n"
            "#   port: 8765\n"
            "#   transport: stdio\n"
        )

    def _generate_wiki_md(self) -> str:
        """Generate wiki.md - LLM agent instructions for wiki maintenance."""
        registry = self._get_prompt_registry()
        return registry.render_document("wiki_schema", version=self._get_version())

    def _analyze_raw(self) -> dict:
        """Analyze raw/ directory structure for init report.
        
        Returns:
            {"total": int, "categories": {name: count, ...}}
        """
        result = {"total": 0, "categories": {}}
        if not self.raw_dir.exists():
            return result

        for item in sorted(self.raw_dir.iterdir()):
            if item.is_dir():
                count = len([f for f in item.rglob("*") if f.is_file() and f.suffix in (".md", ".txt")])
                if count > 0:
                    result["categories"][item.name] = count
                    result["total"] += count
            elif item.suffix in (".md", ".txt", ".pdf", ".html"):
                result["categories"]["(root)"] = result["categories"].get("(root)", 0) + 1
                result["total"] += 1

        return result

    @staticmethod
    def _render_template(name: str, **variables: Any) -> str:
        """Render a template file with Jinja2 variable substitution."""
        from jinja2 import BaseLoader, Environment
        template_path = TEMPLATES_DIR / name
        if not template_path.exists():
            return ""
        content = template_path.read_text()
        env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
        return env.from_string(content).render(**variables)

    def _generate_mcp_config(self, agent: str) -> str:
        """Generate agent-specific MCP configuration JSON."""
        template_map = {
            "opencode": "opencode.json",
            "claude": "claude_mcp.json",
            "codex": "codex_mcp.json",
        }
        template_name = template_map.get(agent)
        if not template_name:
            return ""
        return self._render_template(template_name)

    def _generate_gitignore(self) -> str:
        """Generate .gitignore content."""
        return self._render_template("_gitignore")

    def _generate_skill_files(self) -> list:
        """Generate skill files for CLI fallback mode.

        Creates .agents/skills/llmwikify/ in the project root with:
        - SKILL.md — main entry point with workflows and conventions
        - resources/cli-reference.md — complete CLI command reference

        Returns list of created file paths (relative to project root).
        """
        created = []
        skill_dir = self.root / ".agents" / "skills" / "llmwikify"

        skill_files = {
            ".agents/skills/llmwikify/SKILL.md": "skill_llmwikify/SKILL.md",
            ".agents/skills/llmwikify/resources/cli-reference.md": "skill_llmwikify/resources/cli-reference.md",
        }

        for rel_path, template_name in skill_files.items():
            dest = self.root / rel_path
            if dest.exists():
                continue
            content = self._render_template(template_name)
            if content:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)
                created.append(rel_path)

        return created

    @staticmethod
    def _parse_sections(content: str) -> list:
        """Parse markdown into list of (section_header, section_body).

        Only parses H2 headers (## Header) for top-level sections.
        Ignores headers inside code blocks (``` ... ```) and HTML comments.
        Returns list of tuples: ("Section Name", "section content without header")
        """
        sections = []
        lines = content.split("\n")
        current_header = None
        current_body = []
        in_code_block = False
        in_html_comment = False

        for line in lines:
            stripped = line.strip()

            # Track code block boundaries
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                if current_header is not None:
                    current_body.append(line)
                continue

            # Track HTML comment boundaries (for merge notices)
            if "<!--" in stripped and "-->" not in stripped:
                in_html_comment = True
            if "-->" in stripped:
                in_html_comment = False
                if current_header is not None:
                    current_body.append(line)
                continue

            if in_code_block or in_html_comment:
                if current_header is not None:
                    current_body.append(line)
                continue

            if line.startswith("## ") and not line.startswith("### "):
                if current_header is not None:
                    sections.append((current_header, "\n".join(current_body).strip()))
                current_header = line[3:].strip()
                current_body = []
            elif current_header is not None:
                current_body.append(line)

        if current_header is not None:
            sections.append((current_header, "\n".join(current_body).strip()))

        return sections

    @staticmethod
    def _find_insertion_point(content: str) -> int:
        """Find position to insert new sections.

        Priority: before "## Best Practices", before "## Configuration", else end of file.
        """
        for marker in ["## Best Practices", "## Configuration"]:
            pos = content.find(marker)
            if pos != -1:
                return pos
        return len(content)

    @staticmethod
    def _build_merge_notice(new_sections: list, version: str) -> str:
        """Build the dedup instruction notice for LLM agents.

        The notice is an HTML comment at the top of the merged wiki.md,
        instructing the LLM agent to review and deduplicate new sections.
        After the agent completes deduplication, it should remove both
        the notice and the "## Schema Updates" wrapper.
        """
        section_list = "\n".join(f"  - {s}" for s in new_sections)
        return f"""<!--
  WIKI SCHEMA UPDATE NOTICE
  =========================
  This wiki.md has been updated with new sections from llmwikify v{version}.

  NEW SECTIONS ADDED (please review and deduplicate):
{section_list}

  ACTION REQUIRED:
  1. Review the "## Schema Updates (v{version})" section at the end of this file
  2. If any new sections duplicate existing content, merge them into the existing sections
  3. Remove the "## Schema Updates" section after deduplication
  4. Remove this notice after cleanup is complete

  The new sections contain updated conventions and workflows that may complement
  or replace your existing customizations.
-->

"""

    def _merge_wiki_md(self) -> str:
        """Merge new schema into existing wiki.md.

        Strategy: Simple section collection + dedup notice.
        - Parse H2 section headers from both documents (ignoring code blocks)
        - Collect sections that don't exist in current wiki.md
        - Append new sections wrapped in "## Schema Updates (vX.Y.Z)"
        - Add HTML comment notice at top instructing LLM to deduplicate
        - LLM agent handles deduplication on first read
        - Agent removes notice + Schema Updates wrapper after cleanup
        """
        existing = self.wiki_md_file.read_text()
        new_schema = self._generate_wiki_md()

        existing_sections = self._parse_sections(existing)
        new_sections = self._parse_sections(new_schema)

        existing_headers = {header.lower() for header, _ in existing_sections}

        sections_to_add = [
            (header, body) for header, body in new_sections
            if header.lower() not in existing_headers
        ]

        if not sections_to_add:
            # No new sections, just update version number
            return re.sub(
                r"Generated by llmwikify v[\d.]+",
                f"Generated by llmwikify v{self._get_version()}",
                existing,
            )

        # Build merge notice
        new_section_names = [h for h, _ in sections_to_add]
        notice = self._build_merge_notice(new_section_names, self._get_version())

        # Build new sections content
        new_content = "\n\n".join(
            f"## {header}\n\n{body}" for header, body in sections_to_add
        )

        # Insert before Best Practices / Configuration (or at end)
        insert_pos = self._find_insertion_point(existing)
        before = existing[:insert_pos]
        after = existing[insert_pos:]

        separator = "\n\n" if not before.endswith("\n\n") else ""
        merged = (
            f"{notice}"
            f"{before}"
            f"{separator}"
            f"## Schema Updates (v{self._get_version()})\n\n"
            f"{new_content}\n\n"
            f"---\n\n"
            f"{after}"
        )

        merged = re.sub(
            r"Generated by llmwikify v[\d.]+",
            f"Generated by llmwikify v{self._get_version()}",
            merged,
        )

        return merged

    def ingest_source(self, source: str) -> dict:
        """Ingest a source file and return extracted data for LLM processing.
        
        Does NOT automatically write wiki pages. Returns extracted content
        along with current wiki index so the LLM can decide which pages
        to create/update and how to cross-reference.
        
        All source files are collected into raw/ for centralized management.
        - URL/YouTube: extracted text is saved to raw/
        - Local files outside raw/: copied to raw/
        - Local files already in raw/: no copy needed
        """
        result = extract(source, wiki_root=self.root)

        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error")}

        if not result.text:
            return {"error": "No content extracted"}

        # Collect source file into raw/
        saved_to_raw = False
        already_exists = False
        hint = ""
        source_name = ""

        self.raw_dir.mkdir(parents=True, exist_ok=True)

        if result.source_type in ("url", "youtube"):
            # URL/YouTube: save extracted text to raw/
            safe_name = self._slugify(result.title) + ".md"
            saved_path = self.raw_dir / safe_name

            if saved_path.exists():
                already_exists = True
                source_name = safe_name
                hint = f"Source already exists in raw/{safe_name}"
            else:
                saved_path.write_text(result.text)
                saved_to_raw = True
                source_name = safe_name
                hint = f"Extracted text saved to raw/{safe_name}"
        else:
            # Local file: check if already in raw/
            original_path = Path(source).resolve()
            try:
                original_path.relative_to(self.raw_dir.resolve())
                # File is already inside raw/
                source_name = str(original_path.relative_to(self.raw_dir))
                saved_to_raw = False
                hint = f"Source is already in raw/{source_name}"
            except ValueError:
                # File is outside raw/, copy it in
                safe_name = self._slugify(result.title or original_path.stem) + original_path.suffix
                saved_path = self.raw_dir / safe_name

                if saved_path.exists():
                    already_exists = True
                    source_name = safe_name
                    hint = f"Source already exists in raw/{safe_name}"
                else:
                    # Cross-platform copy: read bytes and write (no permission issues)
                    saved_path.write_bytes(original_path.read_bytes())
                    saved_to_raw = True
                    source_name = safe_name
                    hint = f"Source copied to raw/{safe_name} from {original_path}"

        # Read current index for LLM context
        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()

        # Log the ingest
        log_detail = f"Source ({result.source_type}): {result.title}"
        if saved_to_raw:
            log_detail += f" → raw/{source_name}"
        self.append_log("ingest", log_detail)

        # Compute file metadata for LLM context
        raw_file = self.raw_dir / source_name
        file_size = 0
        word_count = 0
        has_images = False
        image_count = 0

        if raw_file.exists():
            file_size = raw_file.stat().st_size
            word_count = len(result.text.split()) if result.text else 0
            # Detect image references in markdown
            image_refs = re.findall(r'!\[.*?\]\((.*?)\)', result.text or '')
            image_count = len(image_refs)
            has_images = image_count > 0

        return {
            "source_name": source_name,
            "source_raw_path": f"raw/{source_name}",
            "source_type": result.source_type,
            "file_type": self._detect_file_type(source_name),
            "file_size": file_size,
            "word_count": word_count,
            "has_images": has_images,
            "image_count": image_count,
            "text_extracted": bool(result.text),
            "title": result.title,
            "content_preview": (result.text or "")[:200],
            "content": result.text,
            "content_length": len(result.text),
            "metadata": result.metadata,
            "saved_to_raw": saved_to_raw,
            "already_exists": already_exists,
            "hint": hint,
            "current_index": index_content,
            "message": "Source ingested. Read the file to extract key takeaways.",
            "instructions": self._get_prompt_registry().render_text("ingest_instructions"),
        }

    def _llm_process_source(self, source_data: dict) -> dict:
        """Process source with LLM using chained mode: analyze_source → generate_wiki_ops."""
        from ..llm_client import LLMClient

        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()

        max_content_chars = registry.get_params("analyze_source").get("max_content_chars", 8000)
        content = source_data["content"][:max_content_chars]
        content_truncated = len(source_data["content"]) > max_content_chars

        # Read wiki.md schema for page type conventions
        wiki_schema = ""
        if self.wiki_md_file.exists():
            wiki_schema = self.wiki_md_file.read_text()

        analysis_messages = registry.get_messages(
            "analyze_source",
            title=source_data["title"],
            source_type=source_data["source_type"],
            content=content,
            current_index=source_data.get("current_index", ""),
            max_content_chars=max_content_chars,
            content_truncated=content_truncated,
            wiki_schema=wiki_schema,
        )
        analysis_params = registry.get_api_params("analyze_source")

        analysis = self._call_llm_with_retry("analyze_source", analysis_messages, analysis_params)

        errors = registry.validate_output("analyze_source", analysis)
        if errors:
            raise ValueError(f"Analysis validation failed: {'; '.join(errors)}")

        template = registry._load_template("generate_wiki_ops")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)

        ops_messages = registry.get_messages(
            "generate_wiki_ops",
            **dynamic_context,
            analysis_json=json.dumps(analysis, indent=2),
            current_index=source_data.get("current_index", ""),
        )
        ops_params = registry.get_api_params("generate_wiki_ops")

        operations = self._call_llm_with_retry("generate_wiki_ops", ops_messages, ops_params)

        errors = registry.validate_output("generate_wiki_ops", operations)
        if errors:
            raise ValueError(f"Operations validation failed: {'; '.join(errors)}")

        if not isinstance(operations, list):
            raise ValueError(f"Expected list of operations, got {type(operations).__name__}")

        return {
            "status": "success",
            "operations": operations,
            "relations": analysis.get("relations", []),
            "entities": analysis.get("entities", []),
            "claims": analysis.get("claims", []),
            "analysis": analysis,
            "source_title": source_data["title"],
            "mode": "chained",
        }

    def _call_llm_with_retry(
        self,
        prompt_name: str,
        messages: list[dict[str, str]],
        params: dict,
    ) -> Any:
        """Call LLM with retry on validation failure."""
        from ..llm_client import LLMClient

        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()
        retry_config = registry.get_retry_config(prompt_name)
        max_attempts = retry_config.get("max_attempts", 1)

        last_errors: list[str] = []
        for attempt in range(1, max_attempts + 1):
            try:
                result = client.chat_json(messages, **params)

                errors = registry.validate_output(prompt_name, result)
                if not errors:
                    return result

                last_errors = errors
                if attempt < max_attempts:
                    error_text = "\n".join(f"- {e}" for e in errors)
                    retry_prompt = (
                        f"Your previous response had errors:\n{error_text}\n\n"
                        f"Please fix and return a corrected response."
                    )
                    messages = [
                        messages[0],
                        {"role": "user", "content": retry_prompt},
                    ]

            except (ConnectionError, ValueError) as e:
                last_errors = [str(e)]
                if attempt >= max_attempts:
                    raise

        raise ValueError(
            f"LLM failed after {max_attempts} attempts for '{prompt_name}': "
            f"{'; '.join(last_errors)}"
        )

    def execute_operations(self, operations: list) -> dict:
        """Execute a list of wiki operations from LLM processing.
        
        Args:
            operations: List of {action, ...} dicts from _llm_process_source().
        
        Returns:
            Dict with results of each operation.
        """
        results = []
        for op in operations:
            action = op.get("action", "")
            if action == "write_page":
                page_name = op.get("page_name", "")
                content = op.get("content", "")
                if page_name and content:
                    self.write_page(page_name, content)
                    results.append({"action": "write_page", "page": page_name, "status": "done"})
                else:
                    results.append({"action": "write_page", "status": "skipped", "reason": "missing page_name or content"})
            elif action == "log":
                operation = op.get("operation", "")
                details = op.get("details", "")
                if operation and details:
                    self.append_log(operation, details)
                    results.append({"action": "log", "operation": operation, "status": "done"})
                else:
                    results.append({"action": "log", "status": "skipped", "reason": "missing operation or details"})
            else:
                results.append({"action": action, "status": "unknown"})

        return {
            "status": "completed",
            "operations_executed": len(results),
            "results": results,
        }

    def write_relations(self, relations: list, source_file: str | None = None) -> dict:
        """Write extracted relations to the database.
        
        Args:
            relations: List of {source, target, relation, confidence, context} dicts.
            source_file: Original source file name.
        
        Returns:
            Dict with count of relations added.
        """
        if not relations:
            return {"status": "skipped", "count": 0}

        from .relation_engine import RelationEngine

        engine = RelationEngine(self.index, wiki_root=self.root)

        # Enrich with source_file if not present
        for r in relations:
            if "source_file" not in r and source_file:
                r["source_file"] = source_file

        count = engine.add_relations(relations)

        if count == 0 and relations:
            valid_types = engine.get_relation_types()
            return {
                "status": "skipped",
                "count": 0,
                "reason": f"No valid relations added. Valid types: {sorted(valid_types)}",
            }

        return {
            "status": "completed",
            "count": count,
            "source_file": source_file,
        }

    def get_relation_engine(self) -> "RelationEngine":
        """Get the relation engine instance."""
        from .relation_engine import RelationEngine
        return RelationEngine(self.index, wiki_root=self.root)

    def graph_analyze(self) -> dict:
        """Run full knowledge graph analysis.

        Returns suggestions only — never auto-creates pages.
        Respects "stay involved" principle.

        Returns:
            Dict with:
            - centrality: PageRank scores, hubs, authorities
            - communities: Community detection with labels
            - suggestions: Pages to create, links to add
            - stats: Graph statistics
        """
        from .graph_analyzer import GraphAnalyzer

        analyzer = GraphAnalyzer(self)
        return analyzer.analyze()

    def graph_suggested_pages_report(self) -> str:
        """Generate human-readable report of suggested pages."""
        from .graph_analyzer import GraphAnalyzer

        analyzer = GraphAnalyzer(self)
        return analyzer.get_suggested_pages_report()

    def write_page(self, page_name: str, content: str, page_type: str = None) -> str:
        """Write a wiki page.

        Args:
            page_name: Page name. Can be:
                - Pure name: "Risk Parity" (use with page_type)
                - Path: "concepts/Risk Parity" (legacy, still supported)
            content: Page content markdown.
            page_type: Page type from wiki.md Page Types table.
                Dynamically resolved to directory via _load_page_type_mapping().
                If None and page_name has no '/', writes to wiki/ root.

        Examples:
            write_page("Risk Parity", content, page_type="Concept")
            write_page("concepts/Risk Parity", content)  # legacy
        """
        # Security: prevent path traversal
        if ".." in page_name or page_name.startswith("/"):
            raise ValueError(f"Invalid page name: {page_name!r} — path traversal not allowed")

        # If page_name starts with "wiki/", give clear error
        if page_name.startswith("wiki/"):
            raise ValueError(
                f"page_name should NOT include 'wiki/' prefix. "
                f"Use '{page_name[5:]}' instead of '{page_name}'. "
                f"The 'wiki/' directory is added automatically."
            )

        # Resolve directory from page_type or page_name
        if page_type:
            # New API: page_type → directory mapping from wiki.md
            type_to_dir = self._load_page_type_mapping()
            
            # Try exact match first, then case-insensitive
            directory = type_to_dir.get(page_type)
            if directory is None:
                # Case-insensitive fallback
                lower_map = {k.lower(): v for k, v in type_to_dir.items()}
                directory = lower_map.get(page_type.lower())
            
            if directory is None:
                # Ultimate fallback: use page_type lowercased as directory
                directory = page_type.lower()
            
            full_path = f"{directory}/{page_name}"
        elif '/' in page_name:
            # Legacy API: page_name contains directory
            full_path = page_name
        else:
            # No type, no directory → root
            full_path = page_name

        # Decode escape sequences from CLI JSON input: \n -> newline, \t -> tab
        if '\\n' in content or '\\t' in content:
            try:
                content = content.encode('utf-8').decode('unicode_escape')
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass  # Keep original if decoding fails

        page_path = (self.wiki_dir / f"{full_path}.md").resolve()

        # Security: verify resolved path is within wiki/ directory
        try:
            page_path.relative_to(self.wiki_dir.resolve())
        except ValueError:
            raise ValueError(f"Page path escapes wiki/ directory: {full_path!r}")

        page_path.parent.mkdir(parents=True, exist_ok=True)

        if page_path.exists():
            page_path.write_text(content)
            action = "Updated"
        else:
            page_path.write_text(content)
            action = "Created"

        # Update index (use full relative path as page_name for consistency)
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(rel_path[:-3], content, rel_path)  # strip .md

        # Auto-update index.md
        self._update_index_file()

        return f"{action} page: {full_path}"

    def read_page(self, page_name: str, page_type: str = None) -> dict:
        """Read a wiki page with sink status attached.

        Args:
            page_name: Page name. Can be pure name or path.
            page_type: Page type to resolve directory (same as write_page).
        """
        # Backward compat: translate old 'sink/' path to new '.sink/' location
        if page_name.startswith('sink/'):
            page_name = page_name.replace('sink/', '.sink/', 1)

        if page_name.startswith('.sink/') or page_name.startswith('wiki/.sink/'):
            # Extract filename from path (handle both '.sink/X.sink.md' and 'wiki/.sink/X.sink.md')
            sink_name = page_name.rsplit('/', 1)[-1]
            sink_file = self.sink_dir / sink_name
            if not sink_file.exists():
                return {"error": f"Sink file not found: {page_name}"}
            # Remove .sink.md suffix properly
            raw_name = sink_file.name  # e.g., "Query: Gold Mining.sink.md"
            if raw_name.endswith('.sink.md'):
                page_name_from_file = raw_name[:-len('.sink.md')]
            else:
                page_name_from_file = sink_file.stem.replace('.sink', '')

            return {
                "page_name": page_name_from_file,
                "content": sink_file.read_text(),
                "file": str(sink_file),
                "is_sink": True,
            }

        # Resolve directory from page_type if provided
        if page_type and '/' not in page_name:
            type_to_dir = self._load_page_type_mapping()
            directory = type_to_dir.get(page_type)
            if directory is None:
                lower_map = {k.lower(): v for k, v in type_to_dir.items()}
                directory = lower_map.get(page_type.lower())
            if directory is None:
                directory = page_type.lower()
            full_path = f"{directory}/{page_name}"
        else:
            full_path = page_name

        page_path = self.wiki_dir / f"{full_path}.md"

        if not page_path.exists():
            return {"error": f"Page not found: {full_path}"}

        result = {
            "page_name": full_path,
            "content": page_path.read_text(),
            "file": str(page_path),
            "is_sink": False,
        }

        sink_info = self.query_sink.get_info_for_page(full_path)
        result['has_sink'] = sink_info['has_sink']
        result['sink_entries'] = sink_info['sink_entries']

        return result

    def search(self, query: str, limit: int = 10) -> list:
        """Full-text search with sink status attached."""
        results = self.index.search(query, limit)

        for result in results:
            sink_info = self.query_sink.get_info_for_page(result['page_name'])
            result['has_sink'] = sink_info['has_sink']
            result['sink_entries'] = sink_info['sink_entries']

        return results

    def _load_page_type_mapping(self) -> dict[str, str]:
        """Load page type → directory mapping from wiki.md Page Types table.

        Parses wiki.md for tables like:
        | Type | Location | Purpose |
        |------|----------|---------|
        | Source | wiki/sources/{slug}.md | ... |
        | MacroFactor | wiki/factors/{name}.md | ... |

        Returns dict mapping type name → directory name, e.g.:
        {"Source": "sources", "MacroFactor": "factors", ...}
        """
        if not self.wiki_md_file.exists():
            return {}

        content = self.wiki_md_file.read_text()
        type_to_dir: dict[str, str] = {}
        in_page_types = False
        in_table = False

        for line in content.split('\n'):
            # Detect Page Types section headers
            if '## Page Types' in line or '### Custom Page Types' in line:
                in_page_types = True
                in_table = False
                continue

            # Exit when we hit another top-level section
            if in_page_types and line.startswith('## ') and 'Page Types' not in line:
                in_page_types = False
                continue

            if not in_page_types:
                continue

            # Detect table start (separator line)
            if '|' in line and line.strip().startswith('|---') or line.strip().startswith('| -'):
                in_table = True
                continue

            # Parse table rows
            if in_table and '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 3:
                    page_type = parts[0]
                    location = parts[1]

                    # Extract directory from Location pattern like wiki/sources/{slug}.md
                    match = re.search(r'wiki/([^/\{]+)/', location)
                    if match:
                        directory = match.group(1)
                        type_to_dir[page_type] = directory

        return type_to_dir

    def _detect_dated_claims(self) -> list[dict]:
        """Find year mentions in pages that predate latest raw source by 3+ years."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_dated_claims()

    def _detect_query_page_overlap(self) -> list[dict]:
        """Find Query: pages with >=85% keyword Jaccard overlap."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_query_page_overlap()

    def _detect_missing_cross_refs(self) -> list[dict]:
        """Find concepts mentioned in 2+ pages but not wikilinked."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_missing_cross_refs()

    def _detect_potential_contradictions(self) -> list[dict]:
        """Scan wiki pages for potential contradictions."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_potential_contradictions()

    def _detect_data_gaps(self) -> list[dict]:
        """Detect potential data gaps in wiki pages."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_data_gaps()

    def _detect_outdated_pages(self) -> list[dict]:
        """Detect pages that may be outdated based on source dates."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_outdated_pages()

    def _detect_knowledge_gaps(self) -> list[dict]:
        """Detect knowledge gaps across the wiki."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_knowledge_gaps()

    def _detect_redundancy(self) -> list[dict]:
        """Detect potentially redundant or overlapping content."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._detect_redundancy()

    def _llm_generate_investigations(
        self,
        contradictions: list[dict],
        data_gaps: list[dict],
    ) -> dict:
        """Use LLM to generate investigation suggestions."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._llm_generate_investigations(contradictions, data_gaps)

    def _compute_content_hash(self, source_path: str) -> str:
        """Compute SHA-256 hash of a source file's content."""
        import hashlib
        content = (self.root / source_path).read_text()
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _find_source_summary_page(self, source_path: str) -> Path | None:
        """Find the Source summary page for a given raw source.

        Looks in wiki/sources/ for a page that cites the raw source.
        Uses slug of source filename to find the page.
        """
        sources_dir = self.wiki_dir / "sources"
        if not sources_dir.exists():
            return None

        # Generate slug from source path
        slug = self._slugify(Path(source_path).stem)
        
        # Try exact slug match first
        candidate = sources_dir / f"{slug}.md"
        if candidate.exists():
            return candidate

        # Fallback: search for a page that cites this raw source
        source_ref = f"(raw/{Path(source_path).name})"
        for page in sources_dir.rglob("*.md"):
            content = page.read_text()
            if source_ref in content or source_path in content:
                return page

        return None

    def _cache_source_analysis(self, page_path: Path, content_hash: str, analysis: dict) -> None:
        """Embed analysis results as HTML comment in Source summary page."""
        try:
            content = page_path.read_text()
            analysis_json = json.dumps(analysis, ensure_ascii=False)
            comment = f'<!-- llmwikify:analysis {{"version":1,"hash":"{content_hash}","analyzed_at":"{datetime.now(timezone.utc).isoformat()}","data":{analysis_json}}} -->'

            if '<!-- llmwikify:analysis' in content:
                content = re.sub(r'<!-- llmwikify:analysis.*? -->', comment, content, flags=re.DOTALL)
            else:
                content += f'\n{comment}'

            page_path.write_text(content)
        except Exception:
            logger.warning("Failed to cache source analysis for %s", page_path)

    def _get_cached_source_analysis(self, page_path: Path) -> dict | None:
        """Extract cached analysis from Source summary page."""
        try:
            content = page_path.read_text()
            match = re.search(r'<!-- llmwikify:analysis (.*?) -->', content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except Exception:
            logger.debug("Failed to parse cached analysis for %s", page_path)
        return None

    def analyze_source(self, source_path: str, force: bool = False) -> dict:
        """Analyze a source file and cache structured extraction.

        Args:
            source_path: Relative path, e.g., 'raw/article.md'
            force: Force re-analysis even if cached

        Returns:
            Analysis dict with: topics, entities, relations, suggested_pages, etc.
            Or {"status": "skipped", "reason": "..."} if LLM unavailable.
        """
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {"status": "skipped", "reason": "No LLM configured"}

        # Find or create Source summary page
        source_page = self._find_source_summary_page(source_path)

        # Check cache
        if not force and source_page and source_page.exists():
            cached = self._get_cached_source_analysis(source_page)
            if cached:
                current_hash = self._compute_content_hash(source_path)
                if cached.get('hash') == current_hash:
                    return cached.get('data', {})

        # Read source content
        full_path = self.root / source_path
        if not full_path.exists():
            return {"status": "error", "reason": f"Source not found: {source_path}"}

        content = full_path.read_text()
        content_hash = self._compute_content_hash(source_path)

        # Call LLM analyze_source
        registry = self._get_prompt_registry()
        wiki_schema = ""
        if self.wiki_md_file.exists():
            wiki_schema = self.wiki_md_file.read_text()

        messages = registry.get_messages(
            "analyze_source",
            title=source_path,
            source_type="local",
            content=content[:8000],
            current_index=self.index_file.read_text() if self.index_file.exists() else "",
            wiki_schema=wiki_schema,
        )
        params = registry.get_api_params("analyze_source")

        try:
            analysis = client.chat_json(messages, **params)
        except (ConnectionError, TimeoutError, ValueError, OSError):
            return {"status": "error", "reason": "LLM analysis failed"}

        # Cache to Source summary page if it exists
        if source_page and source_page.exists():
            self._cache_source_analysis(source_page, content_hash, analysis)

        return analysis

    def _build_lint_context(self, limit: int = 20) -> str:
        """Build minimal context for LLM lint analysis."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._build_lint_context(limit)

    def _llm_detect_gaps(self, context: str) -> list[dict]:
        """Call LLM to detect gaps between wiki schema and current state."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._llm_detect_gaps(context)

    def _fallback_detect_gaps(self) -> list[dict]:
        """Basic gap detection without LLM."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._fallback_detect_gaps()

    def lint(
        self,
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        generate_investigations: bool = False,
    ) -> dict:
        """Health check the wiki with schema-aware gap detection."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self).lint(
            mode=mode, limit=limit, force=force,
            generate_investigations=generate_investigations,
        )

    def recommend(self) -> dict:
        """Generate smart recommendations."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self).recommend()

    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement.

        Deprecated: Use `lint(format="brief")` instead.
        """
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self).hint()

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._generate_hints()

        if generate_investigations:
            llm_suggestions = self._llm_generate_investigations(contradictions, data_gaps)
            investigations.update(llm_suggestions)

        result = {
            "total_pages": len(self._wiki_pages()),
            "issue_count": len(all_issues),
            "issues": all_issues,
            "mode": mode,
            "schema_source": "wiki.md (direct)",
            "hints": {
                "critical": critical_hints,
                "informational": informational_hints,
            },
            "investigations": investigations,
            "sink_status": sink_status,
            "sink_warnings": sink_warnings,
        }

        # Auto-fix when mode="fix"
        if mode == "fix":
            fix_result = self.fix_wikilinks(dry_run=False)

            # Update index with summaries and grouping
            self._update_index_file()

            result["auto_fix"] = {
                "wikilinks_fixed": fix_result["fixed"],
                "wikilinks_skipped": fix_result["skipped"],
                "wikilinks_ambiguous": fix_result["ambiguous"],
                "wikilink_changes": fix_result["changes"][:20],
                "index_updated": True,
            }

        return result

    def recommend(self) -> dict:
        """Generate smart recommendations."""
        missing_pages = []
        orphan_pages = []

        # Find missing pages (referenced but don't exist)
        link_counts = {}
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        for target, count in link_counts.items():
            if count >= 2:  # Threshold for missing pages
                if self._resolve_wikilink_target(target) is None:
                    missing_pages.append({
                        "page": target,
                        "reference_count": count,
                    })

        # Find orphan pages
        for page in self._wiki_pages():
            page_name = self._page_display_name(page)

            if self._should_exclude_orphan(page_name, page):
                continue

            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_pages.append({"page": page_name})

        return {
            "missing_pages": missing_pages,
            "orphan_pages": orphan_pages,
            "summary": {
                "total_missing_pages": len(missing_pages),
                "total_orphans": len(orphan_pages),
            },
        }

    def status(self) -> dict:
        """Get wiki status."""
        result = {
            "initialized": self.is_initialized(),
            "root": str(self.root),
            "page_count": len(self._wiki_pages()),
            "source_count": len([f for f in self.raw_dir.rglob("*") if f.is_file()]),
            "indexed_pages": self.index.get_page_count() if self.is_initialized() else "N/A",
            "total_links": self.index.get_link_count() if self.is_initialized() else "N/A",
        }

        # Pages by type — return lists of page names (not counts) for Web UI file tree
        pages_by_type = {}
        for subdir in ["sources", "entities", "concepts", "comparisons", "synthesis", "claims"]:
            sub_path = self.wiki_dir / subdir
            if sub_path.exists():
                pages_by_type[subdir] = sorted(
                    str(p.relative_to(self.wiki_dir))[:-3]
                    for p in sub_path.rglob("*.md")
                )
        # Root-level pages (overview, index, log excluded)
        root_pages = [
            str(p.relative_to(self.wiki_dir))[:-3]
            for p in self.wiki_dir.glob("*.md")
            if p.stem not in ("index", "log")
        ]
        if root_pages:
            pages_by_type["root"] = sorted(root_pages)
        result["pages_by_type"] = pages_by_type

        # Graph stats
        if self.is_initialized():
            try:
                engine = self.get_relation_engine()
                stats = engine.get_stats()
                result["graph_stats"] = stats
            except Exception:
                logger.debug("Failed to load graph stats")
                result["graph_stats"] = {"total_relations": 0, "unique_concepts": 0}

        return result

    def append_log(self, operation: str, details: str) -> str:
        """Append entry to wiki log."""
        entry = f"## [{self._now()}] {operation} | {details}\n"
        with open(self.log_file, 'a') as f:
            f.write(entry)
        return "Logged"

    def build_index(self, auto_export: bool = True, output_path: Path | None = None) -> dict:
        """Build reference index."""
        result = self.index.build_index_from_files(self.wiki_dir, batch_size=self._batch_size)

        if auto_export:
            export_path = output_path or self.ref_index_path
            self.index.export_json(export_path)
            result["json_export"] = str(export_path)

        return result

    def export_index(self, output_path: Path) -> dict:
        """Export reference index to JSON."""
        return self.index.export_json(output_path)

    def get_inbound_links(self, page_name: str, include_context: bool = False) -> list:
        """Get pages that link to this page.
        
        Args:
            page_name: Target page name
            include_context: If True, read source files for context around links
        """
        links = self.index.get_inbound_links(page_name)

        if include_context:
            for link in links:
                link['context'] = self._get_link_context(
                    link['source'], link.get('section', '')
                )

        return links

    def get_outbound_links(self, page_name: str, include_context: bool = False) -> list:
        """Get pages that this page links to.
        
        Args:
            page_name: Source page name
            include_context: If True, read source files for context around links
        """
        links = self.index.get_outbound_links(page_name)

        if include_context:
            for link in links:
                link['context'] = self._get_link_context(
                    page_name, link.get('section', ''), link.get('target', '')
                )

        return links

    def _should_exclude_orphan(self, page_name: str, page_path: Path) -> bool:
        """Check if a page should be excluded from orphan detection."""
        page_name_lower = page_name.lower()

        # Check default patterns
        for pattern in self._default_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        # Check user-configured patterns
        for pattern in self._user_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True

        # Check frontmatter
        if page_path.exists():
            content = page_path.read_text()
            for key in self._exclude_frontmatter_keys:
                if f"{key}:" in content:
                    return True

        # Check if in archive directory
        try:
            rel_path = page_path.relative_to(self.wiki_dir)
            for part in rel_path.parts:
                if part.lower() in self._archive_dirs:
                    return True
        except ValueError:
            pass

        return False

    @staticmethod
    def _detect_file_type(filename: str) -> str:
        """Detect file type from extension."""
        ext = Path(filename).suffix.lower()
        type_map = {
            '.md': 'markdown',
            '.markdown': 'markdown',
            '.pdf': 'pdf',
            '.txt': 'text',
            '.html': 'html',
            '.htm': 'html',
            '.csv': 'csv',
            '.json': 'json',
            '.xml': 'xml',
            '.docx': 'docx',
            '.doc': 'doc',
        }
        return type_map.get(ext, 'unknown')

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to URL-friendly slug."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text

    @staticmethod
    def _now() -> str:
        """Get current ISO timestamp."""
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    @staticmethod
    def _get_version() -> str:
        """Get llmwikify version."""
        try:
            from .. import __version__
            return __version__
        except ImportError:
            return "0.11.0"

    def _extract_page_summary(self, page_path: Path, max_len: int = 120) -> str:
        """Extract a one-line summary from a wiki page.

        Priority:
        1. YAML frontmatter 'summary' field
        2. First paragraph under ## Summary section (Source pages)
        3. First paragraph after title/frontmatter
        4. Fallback: page title
        """
        try:
            content = page_path.read_text()
        except OSError:
            return ""

        # Priority 1: YAML frontmatter summary
        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for line in fm_text.split('\n'):
                if line.startswith('summary:'):
                    val = line.split(':', 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val if len(val) <= max_len else val[:max_len - 3] + '...'

        # Priority 2: ## Summary section first paragraph
        summary_match = re.search(r'^## Summary\s*\n(.*?)(?:\n## |\Z)', content, re.MULTILINE | re.DOTALL)
        if summary_match:
            section_text = summary_match.group(1).strip()
            # Take first non-empty line (first paragraph)
            for line in section_text.split('\n'):
                line = line.strip()
                if line and not line.startswith('<!--'):
                    return line if len(line) <= max_len else line[:max_len - 3] + '...'

        # Strip frontmatter for remaining priorities
        body = content
        if fm_match:
            body = content[fm_match.end():]

        # Priority 3: First non-title, non-empty paragraph
        lines = body.split('\n')
        in_title = True
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if in_title and stripped.startswith('#'):
                continue
            if in_title:
                in_title = False
            if stripped.startswith('<!--'):
                continue
            # Clean markdown artifacts
            clean = re.sub(r'\*\*|\*|`', '', stripped).strip()
            if clean:
                return clean if len(clean) <= max_len else clean[:max_len - 3] + '...'

        # Priority 4: Fallback to title
        title_match = re.match(r'^#\s*(.+)', content)
        if title_match:
            return title_match.group(1).strip()

        return page_path.stem

    def _get_source_analysis_summary(self, page_path: Path) -> dict | None:
        """Extract topics and entities from cached Source analysis.

        Returns dict with:
        - topics: list of topic strings
        - entities: list of entity name strings
        Or None if no cached analysis exists.
        """
        cached = self._get_cached_source_analysis(page_path)
        if not cached:
            return None

        data = cached.get('data', {})
        topics = [t for t in data.get('topics', []) if isinstance(t, str)][:5]
        entities = [e['name'] for e in data.get('entities', []) if isinstance(e, dict) and 'name' in e][:5]

        if not topics and not entities:
            return None

        return {'topics': topics, 'entities': entities}

    def _update_index_file(self) -> None:
        """Update index.md with current wiki contents, summaries, and sink status.

        Groups pages by type (Sources, Concepts, Entities, etc.).
        Each page entry includes:
        - Summary extracted from page content
        - For Source pages: topics and entities from cached analysis
        - Word count and link statistics from SQLite index
        - Sink status if applicable
        """
        # Directory label mapping
        dir_labels = {
            'sources': 'Sources',
            'concepts': 'Concepts',
            'entities': 'Entities',
            'comparisons': 'Comparisons',
            'synthesis': 'Synthesis',
            'claims': 'Claims',
        }

        # Group pages by directory
        groups: dict[str, list[str]] = {}
        sink_entries = []
        type_counts: dict[str, int] = {}

        for page in sorted(self.wiki_dir.rglob("*.md")):
            page_path = page.relative_to(self.wiki_dir)

            # Separate sink files
            if page_path.parts[0] == '.sink':
                try:
                    sink_content = page.read_text()
                    entries = len(re.findall(
                        r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]',
                        sink_content, re.MULTILINE
                    ))
                    last_match = re.search(
                        r'^## \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]',
                        sink_content, re.MULTILINE
                    )
                    last_entry = last_match.group(1) if last_match else "unknown"
                    sink_name = page_path.stem.replace('.sink', '')
                    sink_entries.append(
                        f"- [[{sink_name}]] — {entries} pending updates\n"
                        f"  Last entry: {last_entry}"
                    )
                except OSError:
                    pass
                continue

            # Skip index.md and log.md
            if page.name in ("index.md", "log.md"):
                continue

            page_name = str(page_path.with_suffix(''))

            # Determine group
            subdir = page_path.parts[0] if len(page_path.parts) > 1 else ''
            if len(page_path.parts) > 1:
                label = dir_labels.get(subdir, subdir.capitalize())
            else:
                label = 'Overview'

            if label not in groups:
                groups[label] = []
                type_counts[label] = 0
            type_counts[label] += 1

            # Build page entry
            summary = self._extract_page_summary(page)

            # For Source pages, add topics/entities from cached analysis
            analysis_extra = ""
            if subdir == 'sources':
                analysis = self._get_source_analysis_summary(page)
                if analysis:
                    parts = []
                    if analysis['topics']:
                        parts.append(f"📊 Topics: {', '.join(analysis['topics'])}")
                    if analysis['entities']:
                        parts.append(f"👤 Entities: {', '.join(analysis['entities'])}")
                    if parts:
                        analysis_extra = "\n  " + " | ".join(parts)

            # Get stats from SQLite index
            stats_extra = ""
            try:
                cursor = self.index.conn.execute(
                    "SELECT word_count FROM pages WHERE page_name = ?",
                    (page_name,)
                )
                row = cursor.fetchone()
                if row and row['word_count']:
                    wc = row['word_count']
                    wc_str = f"{wc / 1000:.1f}k" if wc >= 1000 else str(wc)
                    stats_extra = f" | 📝 {wc_str} words"
            except Exception:
                logger.debug("Failed to get word count for %s", page_name)

            # Link counts
            try:
                in_count = len(self.index.get_inbound_links(page_name))
                out_count = len(self.index.get_outbound_links(page_name))
                if in_count > 0 or out_count > 0:
                    link_str = f"🔗 {out_count} out"
                    if in_count > 0:
                        link_str += f" | {in_count} in"
                    stats_extra = f" | {link_str}" + stats_extra
            except Exception:
                logger.debug("Failed to get link counts for %s", page_name)

            # Sink status
            sink_marker = ""
            try:
                sink_info = self.query_sink.get_info_for_page(page_name)
                if sink_info['has_sink']:
                    sink_marker = f" 📥 {sink_info['sink_entries']} pending"
            except Exception:
                logger.debug("Failed to get sink info for %s", page_name)

            entry = f"- [[{page_name}]] - {summary}{sink_marker}"
            if analysis_extra or stats_extra:
                entry += f"\n  {analysis_extra}{stats_extra}".lstrip()

            groups[label].append(entry)

        # Build index content
        total = sum(type_counts.values())
        type_summary = " | ".join(f"{label}: {count}" for label, count in type_counts.items() if count > 0)

        index_content = (
            f"# Wiki Index\n\n"
            f"Last updated: {self._now()}\n\n"
            f"Total pages: {total}"
            + (f" — {type_summary}" if type_summary else "")
            + f"\n\n---\n\n"
        )

        # Ordered section headers
        section_order = ['Sources', 'Concepts', 'Entities', 'Comparisons', 'Synthesis', 'Claims', 'Overview']
        remaining = [k for k in groups if k not in section_order]
        ordered_sections = section_order + sorted(remaining)

        has_content = False
        for section in ordered_sections:
            if section not in groups or not groups[section]:
                continue
            has_content = True
            count = type_counts.get(section, len(groups[section]))
            index_content += f"## {section} ({count})\n\n"
            index_content += '\n\n'.join(groups[section]) + '\n\n'

        if not has_content:
            index_content += "*(No pages yet)*\n\n"

        # Pending Sink Buffers
        if sink_entries:
            index_content += "## Pending Sink Buffers 📥\n\n"
            index_content += '\n\n'.join(sink_entries) + '\n'

        self.index_file.write_text(index_content)

    def _get_link_context(self, source_page: str, section: str, target_page: str = "", context_chars: int = 80) -> str:
        """Extract context around a wikilink in source file.
        
        Args:
            source_page: Source page name
            section: Section header (e.g., '#Overview')
            target_page: Target page name (for outbound links)
            context_chars: Characters to show before/after link
        
        Returns:
            Context string or empty if not found
        """
        source_path = self.wiki_dir / f"{source_page}.md"
        if not source_path.exists():
            return ""

        try:
            content = source_path.read_text()
        except OSError:
            return ""

        # If section specified, find that section
        if section:
            section_name = section.lstrip('#')
            pattern = rf'^#+\s*{re.escape(section_name)}'
            match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
            if match:
                start = match.end()
                next_section = re.search(r'^#+\s+', content[start:], re.MULTILINE)
                if next_section:
                    content = content[start:start+next_section.start()]
                else:
                    content = content[start:]

        # Find the wikilink
        search_target = target_page if target_page else source_page
        link_pattern = r'\[\[' + re.escape(search_target) + r'(?:[^\]]*)?\]\]'
        match = re.search(link_pattern, content)

        if match:
            start = max(0, match.start() - context_chars)
            end = min(len(content), match.end() + context_chars)
            context = content[start:end].strip()
            # Replace newlines with spaces for display
            context = ' '.join(context.split())
            if start > 0:
                context = "..." + context
            if end < len(content):
                context = context + "..."
            return context

        return ""

    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement.
        
        Deprecated: Use `lint(format="brief")` instead. This method will be
        removed in a future version.
        """
        warnings.warn(
            "hint() is deprecated; use wiki.lint(format='brief') instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._generate_hints()

    def _generate_hints(self) -> dict:
        """Internal: generate smart suggestions for wiki improvement."""
        hints = []

        # Check for orphan pages
        orphan_count = 0
        for page in self._wiki_pages():
            page_name = self._page_display_name(page)
            if self._should_exclude_orphan(page_name, page):
                continue
            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_count += 1

        if orphan_count > 0:
            hints.append({
                "type": "orphan",
                "priority": "medium",
                "message": f"You have {orphan_count} orphan page(s). Consider adding cross-references to connect them.",
            })

        # Check for missing pages
        link_counts = {}
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1

        missing = []
        for target, count in link_counts.items():
            if count >= 2:
                if self._resolve_wikilink_target(target) is None:
                    missing.append(target)

        if missing:
            hints.append({
                "type": "missing",
                "priority": "high",
                "message": f"Pages referenced but don't exist: {', '.join(missing[:5])}",
            })

        # Check wiki size
        page_count = len(self._wiki_pages())
        if page_count < 5:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is small. Consider ingesting more sources to build knowledge.",
            })
        elif page_count < 20:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is growing well. Consider running lint to check health.",
            })

        # Check for broken links
        broken_count = 0
        for page in self._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target in (self._index_page_name, self._log_page_name):
                    continue
                if self._resolve_wikilink_target(target) is None:
                    broken_count += 1

        if broken_count > 0:
            hints.append({
                "type": "broken_links",
                "priority": "high",
                "message": f"Found {broken_count} broken link(s). Consider fixing or removing them.",
            })

        return {
            "hints": hints,
            "summary": {
                "total_hints": len(hints),
                "high_priority": sum(1 for h in hints if h['priority'] == 'high'),
            }
        }

    def read_schema(self) -> dict:
        """Read wiki.md (schema/conventions file).
        
        Returns:
            Dict with 'content', 'file', and a 'hint' reminding the LLM
            to save a copy before making changes.
        """
        if not self.wiki_md_file.exists():
            return {"error": "wiki.md not found. Run init() first."}

        return {
            "content": self.wiki_md_file.read_text(),
            "file": str(self.wiki_md_file),
            "hint": "Tip: Save a copy of the current content before making changes to wiki.md",
        }

    def update_schema(self, content: str) -> dict:
        """Update wiki.md with new conventions/workflows.
        
        Validates format but does not block writing. Returns warnings
        for issues and suggestions for post-update actions.
        
        Args:
            content: New wiki.md content.
        
        Returns:
            Dict with 'status', 'file', optional 'warnings' and 'suggestions'.
        """
        if not self.wiki_md_file.exists():
            return {"error": "wiki.md not found. Run init() first."}

        # Format validation (warnings only, does not block)
        warnings = []
        if not content.strip().startswith("#"):
            warnings.append("Missing title header (should start with #)")
        if len(content.strip()) < 50:
            warnings.append("Content seems too short for a schema file")

        self.wiki_md_file.write_text(content)

        result = {
            "status": "updated",
            "file": str(self.wiki_md_file),
            "suggestions": [
                "Review existing wiki pages to ensure compliance with new conventions",
                "Update pages that may conflict with new workflows or linking rules",
            ],
        }

        if warnings:
            result["warnings"] = warnings

        return result

    def _llm_generate_synthesize_answer(
        self,
        query: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
    ) -> dict:
        """Use LLM to generate a structured answer for a query.
        
        This method reads the provided source pages and raw sources,
        injects wiki context, and calls the LLM to produce a well-structured
        answer suitable for wiki synthesis.
        
        Args:
            query: The question to answer.
            source_pages: Wiki page names to use as context.
            raw_sources: Raw source file paths to use as context.
        
        Returns:
            Dict with 'answer' (str), 'suggested_page_name' (optional str),
            and 'source_citations' (list of page names referenced).
        """
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": "LLM client not available",
            }

        registry = self._get_prompt_registry()

        # Read source page contents
        source_page_data = []
        for page_name in (source_pages or []):
            page_path = self.wiki_dir / f"{page_name}.md"
            if page_path.exists():
                source_page_data.append({
                    "name": page_name,
                    "content": page_path.read_text(),
                })

        # Read raw source contents
        raw_source_data = []
        for raw_path in (raw_sources or []):
            full_path = self.root / raw_path
            if full_path.exists():
                raw_source_data.append({
                    "name": raw_path,
                    "content": full_path.read_text(),
                })

        # Inject dynamic context from wiki state
        template = registry._load_template("wiki_synthesize")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)

        # Build variables for prompt rendering
        variables = {
            **dynamic_context,
            "query": query,
            "source_pages": source_page_data,
            "raw_sources": raw_source_data,
        }

        messages = registry.get_messages("wiki_synthesize", **variables)
        params = registry.get_api_params("wiki_synthesize")

        try:
            result = client.chat_json(messages, **params)

            errors = registry.validate_output("wiki_synthesize", result)
            if errors:
                return {
                    "answer": "",
                    "suggested_page_name": "",
                    "source_citations": [],
                    "warning": f"LLM output validation failed: {'; '.join(errors)}",
                }

            return {
                "answer": result.get("answer", ""),
                "suggested_page_name": result.get("suggested_page_name", ""),
                "source_citations": result.get("source_citations", []),
            }
        except (ConnectionError, TimeoutError, ValueError, OSError) as e:
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": f"LLM synthesis generation failed: {e}",
            }

    def synthesize_query(
        self,
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
        page_name: str | None = None,
        auto_link: bool = True,
        auto_log: bool = True,
        mode: str = "sink",
        merge_or_replace: str | None = None,
    ) -> dict:
        """Save a query answer as a new wiki page.
        
        Implements the Query compounding cycle: answers filed back into the wiki
        as persistent pages, just like ingested sources.
        
        Args:
            query: Original question that was asked.
            answer: LLM-generated answer content (markdown).
            source_pages: Wiki pages referenced to generate this answer.
            raw_sources: Raw source files referenced (e.g., 'raw/article.md').
            page_name: Custom page name. Auto-generated as 'Query: {topic}' if omitted.
            auto_link: Automatically add source_pages as [[wikilinks]] in Sources section.
            auto_log: Automatically append to log.md.
            mode: Strategy when similar page exists:
                "sink" (default) — append to sink buffer (duplicates auto-compressed)
                "update" — overwrite the formal page with comprehensive answer
            merge_or_replace: Deprecated. Use `mode` instead.
                Maps: "sink"→"sink", "merge"/"replace"→"update".
        
        Returns:
            Dict with status, page_name, page_path, sources info, hint about duplicates.
        """
        source_pages = source_pages or []
        raw_sources = raw_sources or []

        # Backward compatibility: merge_or_replace → mode
        if merge_or_replace is not None:
            mode = "update" if merge_or_replace in ("merge", "replace") else "sink"

        similar_page = self._find_similar_query_page(query)
        hint = ""

        if similar_page and mode == "update":
            similar_name = similar_page['page_name']
            page_name = similar_name
            page_path = self.wiki_dir / f"{page_name}.md"

            if auto_link:
                answer = self._append_sources_section(
                    answer, query, source_pages, raw_sources
                )

            page_path.write_text(answer)

            rel_path = str(page_path.relative_to(self.wiki_dir))
            self.index.upsert_page(rel_path[:-3], answer, rel_path)
            self._update_index_file()

            status = "updated"
            message = f"Updated query page: {page_name}"

        elif similar_page:
            similar_name = similar_page['page_name']
            sink_path = self.query_sink.append_to_sink(
                similar_name, query, answer, source_pages, raw_sources
            )
            self._update_index_file()

            hint = {
                "type": "similar_page_exists",
                "page_name": similar_name,
                "preview": similar_page['preview'][:100],
                "word_count": similar_page['word_count'],
                "created": similar_page['created'],
                "score": similar_page['score'],
                "action_taken": "appended_to_sink",
                "sink_path": sink_path,
                "observation": (
                    f"A page on this topic exists: '{similar_name}' ({similar_page['word_count']} words). "
                    f"Preview: '{similar_page['preview'][:100]}'. "
                    f"Your answer has been saved to the sink buffer. "
                    f"When ready to integrate, read both and synthesize a comprehensive update."
                ),
                "options": [
                    f"Read the existing page: wiki_read_page('{similar_name}')",
                    f"Read pending entries: wiki_read_page('wiki/.sink/{similar_name}.sink.md')",
                    "Update formal page: wiki_synthesize(..., mode='update')",
                    "Or let the sink accumulate for later review during lint",
                ],
            }

            page_name = similar_name
            page_path = self.root / sink_path

            status = "sunk"
            message = f"Appended to sink for: {similar_name}"

        else:
            # Create new page
            page_name = page_name or self._generate_query_page_name(query)
            page_path = self.wiki_dir / f"{page_name}.md"

            # Handle name collision with non-query pages
            counter = 1
            while page_path.exists():
                base = page_name
                page_name = f"{base} ({counter})"
                page_path = self.wiki_dir / f"{page_name}.md"
                counter += 1

            self._create_query_page(page_path, page_name, answer, query, source_pages, raw_sources, auto_link)
            status = "created"
            message = f"Created query page: {page_name}"

        # Auto-log
        logged = False
        if auto_log:
            if status == "sunk":
                log_detail = f"{query} → [sink] (see wiki/.sink/{similar_page['page_name']}.sink.md)"
            elif status == "updated":
                log_detail = f"{query} → [[{page_name}]] ({status})"
            else:
                log_detail = f"{query} → [[{page_name}]]"
            self.append_log("query", log_detail)
            logged = True

        hint_str = hint if isinstance(hint, str) else json.dumps(hint, indent=2)

        return {
            "status": status,
            "page_name": page_name,
            "page_path": str(page_path.relative_to(self.root)),
            "source_pages": source_pages,
            "raw_sources": raw_sources,
            "logged": logged,
            "hint": hint_str,
            "message": message,
        }

    def _generate_query_page_name(self, query: str) -> str:
        """Generate a page name from a query string.
        
        Extracts topic (first 50 chars, slugified) and prefixes with 'Query: '.
        """
        topic = query.strip()[:50].strip()
        # Capitalize first letter of each word for readability
        topic = topic.title()
        # Remove trailing punctuation
        topic = topic.rstrip(".,;:!?")
        return f"Query: {topic}"

    def _find_similar_query_page(self, query: str) -> dict | None:
        """Find an existing query page with similar topic.
        
        Searches for pages starting with 'Query: ' that share significant
        keywords with the given query.
        
        Returns:
            Dict with page_name, preview, key_topics, word_count, created, score.
            None if no similar page found.
        """
        if not self.wiki_dir.exists():
            return None

        stop_words = {"what", "is", "the", "a", "an", "how", "do", "does", "why",
                       "can", "could", "would", "should", "will", "did", "are", "was",
                       "were", "be", "been", "being", "have", "has", "had", "of", "to",
                       "in", "for", "on", "with", "at", "by", "from", "and", "or", "not",
                       "but", "if", "then", "than", "so", "as", "about", "compare",
                       "what's", "how's", "tell", "me", "explain"}
        keywords = set(
            w.lower().strip(".,;:!?\"'()[]{}")
            for w in query.split()
            if w.lower() not in stop_words and len(w) > 2
        )

        if not keywords:
            return None

        best_match = None
        best_score = 0

        for page in self.wiki_dir.rglob("*.md"):
            page_name = page.stem

            if not page_name.startswith("Query:"):
                continue

            page_keywords = set(
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in stop_words and len(w) > 2
            )

            if not page_keywords:
                continue

            overlap = len(keywords & page_keywords)
            union = len(keywords | page_keywords)
            score = overlap / union if union > 0 else 0

            try:
                content = page.read_text()
                content_keywords = set(
                    w.lower() for w in re.findall(r'\b\w{4,}\b', content)
                    if w.lower() not in stop_words
                )
                content_overlap = len(keywords & content_keywords)
                content_score = content_overlap / len(keywords) if keywords else 0
                score = max(score, content_score * 0.8)
            except OSError:
                pass

            if score > best_score and score >= 0.3:
                best_score = score

                preview = content.split('\n')[-1] if '\n' in content else content
                for line in content.split('\n'):
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#') and not stripped.startswith('---'):
                        preview = stripped[:200]
                        break

                key_topics = list(page_keywords)[:5]
                word_count = len(content.split())

                try:
                    created = datetime.fromtimestamp(
                        page.stat().st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except (OSError, ValueError, OverflowError):
                    created = "unknown"

                best_match = {
                    "page_name": page_name,
                    "preview": preview,
                    "key_topics": key_topics,
                    "word_count": word_count,
                    "created": created,
                    "score": round(score, 3),
                }

        return best_match

    def _create_query_page(
        self,
        page_path: Path,
        page_name: str,
        answer: str,
        query: str,
        source_pages: list[str],
        raw_sources: list[str],
        auto_link: bool,
    ) -> None:
        """Create a new query page with sources section."""
        content = answer

        if auto_link and (source_pages or raw_sources):
            content = self._append_sources_section(content, query, source_pages, raw_sources)

        page_path.write_text(content)

        # Index the page
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(rel_path[:-3], content, rel_path)
        self._update_index_file()

    def _append_sources_section(
        self,
        answer: str,
        query: str,
        source_pages: list[str],
        raw_sources: list[str],
    ) -> str:
        """Append structured Sources section to answer content."""
        sources_section = "\n\n---\n\n## Sources\n\n"

        # Query metadata
        sources_section += "### Query\n"
        sources_section += f"- **Question**: {query}\n"
        sources_section += f"- **Generated**: {self._now()}\n"

        # Wiki pages
        if source_pages:
            sources_section += "\n### Wiki Pages Referenced\n"
            for page in source_pages:
                sources_section += f"- [[{page}]]\n"

        # Raw sources
        if raw_sources:
            sources_section += "\n### Raw Sources\n"
            for raw_path in raw_sources:
                # Extract filename for display
                filename = Path(raw_path).name
                sources_section += f"- [Source: {filename}]({raw_path})\n"

        return answer + sources_section

    # -- QuerySink delegation --

    def read_sink(self, page_name: str) -> dict:
        """Read all entries from a query sink file (hash references resolved)."""
        return self.query_sink.read(page_name)

    def sink_status(self) -> dict:
        """Overview of all query sinks with entry counts and urgency."""
        return self.query_sink.status()

    def suggest_synthesis(self, source_name: str | None = None) -> dict:
        """Analyze sources and generate cross-source synthesis suggestions.

        This method compares new or existing sources against the wiki
        and returns suggestions (not auto-executed). Respects the
        "stay involved" principle — human decides what to do with suggestions.

        Args:
            source_name: Specific source to analyze, or None for all unanalyzed sources.

        Returns:
            Dict with synthesis suggestions:
            - suggestions: list of synthesis suggestions
            - summary: human-readable summary
            - sources_analyzed: number of sources analyzed
        """
        from .synthesis_engine import SynthesisEngine

        engine = SynthesisEngine(self)
        all_suggestions = []

        if source_name:
            # Analyze specific source
            analysis = self.analyze_source(source_name)
            if analysis.get("status") in ("error", "skipped"):
                return {
                    "error": f"Failed to analyze {source_name}: {analysis.get('reason')}",
                    "suggestions": [],
                    "sources_analyzed": 0,
                }

            suggestion = engine.analyze_new_source(analysis, source_name)
            all_suggestions.append(suggestion)
        else:
            # Analyze all sources that haven't been synthesized
            sources_dir = self.raw_dir
            if not sources_dir.exists():
                return {
                    "suggestions": [],
                    "sources_analyzed": 0,
                    "summary": "No raw sources found",
                }

            sources = [f for f in sources_dir.rglob("*") if f.is_file()]
            analyzed_count = 0

            for source_file in sources:
                rel_path = str(source_file.relative_to(self.root))
                try:
                    analysis = self.analyze_source(rel_path)
                    if analysis.get("status") not in ("error", "skipped"):
                        suggestion = engine.analyze_new_source(analysis, rel_path)
                        all_suggestions.append(suggestion)
                        analyzed_count += 1
                except Exception:
                    logger.warning("Source analysis failed for %s", source_file)

        # Generate summary
        total_suggestions = sum(
            len(s.get("suggested_updates", [])) +
            len(s.get("new_contradictions", [])) +
            len(s.get("knowledge_gaps", []))
            for s in all_suggestions
        )

        return {
            "suggestions": all_suggestions,
            "sources_analyzed": len(all_suggestions),
            "total_suggestions": total_suggestions,
            "summary": f"Analyzed {len(all_suggestions)} source(s), generated {total_suggestions} suggestion(s)",
        }

    def close(self):
        """Close database connections."""
        if self._index:
            self._index.close()
