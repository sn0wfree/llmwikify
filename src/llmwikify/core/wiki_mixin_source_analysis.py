"""Wiki source analysis mixin — source file analysis, caching, summary pages."""

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class WikiSourceAnalysisMixin:
    """Source analysis: caching, finding summary pages, content hashing."""

    def _compute_content_hash(self, source_path: str) -> str:
        """Compute SHA-256 hash of a source file's content."""
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

        slug = self._slugify(Path(source_path).stem)
        
        candidate = sources_dir / f"{slug}.md"
        if candidate.exists():
            return candidate

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
            from datetime import datetime, timezone
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
            logger.warning("Failed to parse cached analysis for %s", page_path)
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

        source_page = self._find_source_summary_page(source_path)

        if not force and source_page and source_page.exists():
            cached = self._get_cached_source_analysis(source_page)
            if cached:
                current_hash = self._compute_content_hash(source_path)
                if cached.get('hash') == current_hash:
                    return cached.get('data', {})

        full_path = self.root / source_path
        if not full_path.exists():
            return {"status": "error", "reason": f"Source not found: {source_path}"}

        content = full_path.read_text()
        content_hash = self._compute_content_hash(source_path)

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

        if source_page and source_page.exists():
            self._cache_source_analysis(source_page, content_hash, analysis)

        return analysis
