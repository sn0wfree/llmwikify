"""Wiki schema mixin — wiki.md schema reading, updating, page type mapping."""

import logging
import re

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiSchemaMixin(WikiProtocol):
    """Schema (wiki.md) reading, updating, and page type mapping."""

    def _load_page_type_mapping(self) -> dict[str, str]:
        """Load page type → directory mapping from wiki.md Page Types table.

        Delegates to the backend which parses the Page Types table.
        """
        return self._get_page_type_mapping()

    def read_schema(self) -> dict:
        """Read wiki.md (schema/conventions file).

        Returns:
            Dict with 'content', 'file', and a 'hint' reminding the LLM
            to save a copy before making changes.
        """
        if not self.wiki_md_file.exists():
            return {"error": "wiki.md not found. Run init() first."}

        return {
            "content": self._get_wiki_md_content(),
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

        self._write_wiki_md_content(content)

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
