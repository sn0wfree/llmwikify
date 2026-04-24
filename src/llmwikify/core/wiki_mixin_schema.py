"""Wiki schema mixin — wiki.md schema reading, updating, page type mapping."""

import logging
import re

logger = logging.getLogger(__name__)


class WikiSchemaMixin:
    """Schema (wiki.md) reading, updating, and page type mapping."""

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
            if '## Page Types' in line or '### Custom Page Types' in line:
                in_page_types = True
                in_table = False
                continue

            if in_page_types and line.startswith('## ') and 'Page Types' not in line:
                in_page_types = False
                continue

            if not in_page_types:
                continue

            if '|' in line and line.strip().startswith('|---') or line.strip().startswith('| -'):
                in_table = True
                continue

            if in_table and '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 3:
                    page_type = parts[0]
                    location = parts[1]

                    match = re.search(r'wiki/([^/\{]+)/', location)
                    if match:
                        directory = match.group(1)
                        type_to_dir[page_type] = directory

        return type_to_dir

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

        warnings_list = []
        if not content.strip().startswith("#"):
            warnings_list.append("Missing title header (should start with #)")
        if len(content.strip()) < 50:
            warnings_list.append("Content seems too short for a schema file")

        self.wiki_md_file.write_text(content)

        result = {
            "status": "updated",
            "file": str(self.wiki_md_file),
            "suggestions": [
                "Review existing wiki pages to ensure compliance with new conventions",
                "Update pages that may conflict with new workflows or linking rules",
            ],
        }

        if warnings_list:
            result["warnings"] = warnings_list

        return result
