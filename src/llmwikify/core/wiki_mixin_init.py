"""Wiki init mixin — directory structure, core files, MCP config, skill files."""

import logging

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiInitMixin(WikiProtocol):
    """Wiki initialization: directories, core files, MCP config, skill files."""

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
            agent: Agent type for MCP config generation. One of: opencode, claude, codex, generic.
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
        result: dict[str, Any] = {"total": 0, "categories": {}}
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
        self.root / ".agents" / "skills" / "llmwikify"

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
        import re
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
            return re.sub(
                r"Generated by llmwikify v[\d.]+",
                f"Generated by llmwikify v{self._get_version()}",
                existing,
            )

        new_section_names = [h for h, _ in sections_to_add]
        notice = self._build_merge_notice(new_section_names, self._get_version())

        new_content = "\n\n".join(
            f"## {header}\n\n{body}" for header, body in sections_to_add
        )

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
