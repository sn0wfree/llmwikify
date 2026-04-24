"""Wiki link mixin — wikilink resolution, fixing, inbound/outbound links."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class WikiLinkMixin:
    """Wikilink resolution, fixing, and link context methods."""

    def _resolve_wikilink_target(self, target: str) -> Path | None:
        """Resolve a wikilink target to a file path.

        Resolution order:
        1. Direct path (e.g., "concepts/Factor Investing")
        2. SQLite index lookup (authoritative, supports all formats)
        """
        direct = self.wiki_dir / f"{target}.md"
        if direct.exists():
            return direct

        try:
            file_path = self.index.resolve_by_name(target)
            if file_path:
                return self.wiki_dir / file_path
        except Exception:
            logger.warning("Index lookup failed for wikilink: %s", target)

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
                target = self._parse_wikilink_target(link)
                if target in (self._index_page_name, self._log_page_name):
                    continue

                if '/' in target:
                    continue
                if (self.wiki_dir / f"{target}.md").exists():
                    continue

                matches = list(self.wiki_dir.rglob(f"{target}.md"))

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

                rel_path = str(matches[0].relative_to(self.wiki_dir))[:-3]

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
                rel_path = str(page.relative_to(self.wiki_dir))
                self.index.upsert_page(rel_path[:-3], new_content, rel_path)

        return {**stats, "changes": changes}

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

        search_target = target_page if target_page else source_page
        link_pattern = r'\[\[' + re.escape(search_target) + r'(?:[^\]]*)?\]\]'
        match = re.search(link_pattern, content)

        if match:
            start = max(0, match.start() - context_chars)
            end = min(len(content), match.end() + context_chars)
            context = content[start:end].strip()
            context = ' '.join(context.split())
            if start > 0:
                context = "..." + context
            if end < len(content):
                context = context + "..."
            return context

        return ""
