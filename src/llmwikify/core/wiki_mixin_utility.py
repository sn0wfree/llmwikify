"""Wiki utility mixin — path resolution, slug generation, timestamps, templates."""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class WikiUtilityMixin:
    """Utility methods shared across Wiki operations."""

    @staticmethod
    def _parse_wikilink_target(link: str) -> str:
        """Extract the target page name from a wikilink string.

        Handles aliases ([[Target|Display]]) and sections ([[Target#Section]]).
        Returns the clean target page name.
        """
        return link.split('|')[0].split('#')[0].strip()

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
    def _render_template(name: str, **variables: Any) -> str:
        """Render a template file with Jinja2 variable substitution."""
        from jinja2 import BaseLoader, Environment
        template_path = TEMPLATES_DIR / name
        if not template_path.exists():
            return ""
        content = template_path.read_text()
        env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)
        return env.from_string(content).render(**variables)

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

            if stripped.startswith("```"):
                in_code_block = not in_code_block
                if current_header is not None:
                    current_body.append(line)
                continue

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
        """Build the dedup instruction notice for LLM agents."""
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
