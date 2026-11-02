"""Wiki source analysis mixin — source file analysis, caching, summary pages."""

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path

from llmwikify.kernel.storage.backend import is_path_excluded

from ...protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiSourceAnalysisMixin(WikiProtocol):
    """Source analysis: caching, finding summary pages, content hashing."""

    def _compute_content_hash(self, source_path: str) -> str:
        """Compute SHA-256 hash of a source file's content."""
        content = (self.root / source_path).read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _find_source_summary_page(self, source_path: str) -> Path | None:
        """Find the Source summary page for a given raw source.

        Looks in wiki/sources/ for a page that cites the raw source.
        Uses slug of source filename to find the page.
        """
        return self._build_source_summary_map([source_path]).get(source_path)

    def _build_source_summary_map(
        self, source_paths: Sequence[str]
    ) -> dict[str, Path | None]:
        """Map each raw source path to its Source summary page (None if none).

        One pass over ``wiki/sources/`` shared by every path, instead of one
        full directory scan per path. Per-path semantics are identical to
        :meth:`_find_source_summary_page`:

        1. slug fast path — ``sources/<slug>.md`` exists → that page;
        2. otherwise the first page (in ``rglob`` order, skipping excluded
           paths) whose content contains ``(raw/<basename>)`` or the source
           path itself.
        """
        resolved: dict[str, Path | None] = {}
        sources_dir = self.wiki_dir / "sources"
        if not sources_dir.exists():
            return dict.fromkeys(source_paths)

        pending: list[str] = []
        source_refs: dict[str, str] = {}
        for source_path in source_paths:
            slug = self._slugify(Path(source_path).stem)
            candidate = sources_dir / f"{slug}.md"
            if candidate.exists():
                resolved[source_path] = candidate
            else:
                pending.append(source_path)
                source_refs[source_path] = f"(raw/{Path(source_path).name})"

        if pending:
            for page in sources_dir.rglob("*.md"):
                if is_path_excluded(page):
                    continue
                content = page.read_text(encoding="utf-8", errors="replace")
                for source_path in pending[:]:
                    if source_refs[source_path] in content or source_path in content:
                        resolved[source_path] = page
                        pending.remove(source_path)
                if not pending:
                    break

        for source_path in pending:
            resolved[source_path] = None
        return {path: resolved.get(path) for path in source_paths}

    def _cache_source_analysis(
        self, page_path: Path, content_hash: str, analysis: dict
    ) -> None:
        """Embed analysis results as HTML comment in Source summary page.

        Delegates to the backend which handles the read/modify/write
        of the analysis HTML comment.
        """
        try:
            key = str(page_path.relative_to(self.wiki_dir))[:-3]
            self._backend.put_source_cache(key, content_hash, analysis)
        except (ValueError, OSError) as e:
            logger.warning("Failed to cache source analysis for %s: %s", page_path, e)

    def _get_cached_source_analysis(self, page_path: Path) -> dict | None:
        """Extract cached analysis from Source summary page.

        Delegates to the backend which reads and parses the
        analysis HTML comment.
        """
        try:
            key = str(page_path.relative_to(self.wiki_dir))[:-3]
            return self._get_source_cache(key)
        except (ValueError, OSError) as e:
            logger.warning("Failed to parse cached analysis for %s: %s", page_path, e)
        return None

    def analyze_source(
        self,
        source_path: str,
        force: bool = False,
        section_metadata: dict | None = None,
    ) -> dict:
        """Analyze a source file and cache structured extraction.

        Uses two-phase analysis:
        1. Extract section metadata (pure computation)
        2. LLM selects relevant sections
        3. Targeted reading of selected sections
        4. Full analysis on selected content

        Args:
            source_path: Relative path, e.g., 'raw/article.md'
            force: Force re-analysis even if cached
            section_metadata: Pre-computed section metadata (optional, extracts if not provided)

        Returns:
            Analysis dict with: topics, entities, relations, suggested_pages, etc.
            Or {"status": "skipped", "reason": "..."} if LLM unavailable.
        """
        try:
            from .....foundation.llm import LLMClient

            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {"status": "skipped", "reason": "No LLM configured"}

        source_page = self._find_source_summary_page(source_path)

        if not force and source_page and source_page.exists():
            cached = self._get_cached_source_analysis(source_page)
            if cached:
                current_hash = self._compute_content_hash(source_path)
                if cached.get("hash") == current_hash:
                    return cached.get("data", {})

        full_path = self.root / source_path
        if not full_path.exists():
            return {"status": "error", "reason": f"Source not found: {source_path}"}

        content = full_path.read_text(encoding="utf-8")
        content_hash = self._compute_content_hash(source_path)

        if section_metadata is None:
            section_metadata = self.extract_section_metadata(content, source_path)

        max_chars = 32000
        selected_sections = self._select_sections(
            section_metadata=section_metadata,
            content_type="local",
        )

        targeted_content, content_truncated = self.targeted_read(
            content=content,
            selected_sections=selected_sections.get("selected_sections", []),
            max_chars=max_chars,
        )

        registry = self._get_prompt_registry()
        wiki_schema = ""
        if self.wiki_md_file.exists():
            wiki_schema = self._get_wiki_md_content()

        messages = registry.get_messages(
            "analyze_source",
            title=source_path,
            source_type="local",
            content=targeted_content,
            current_index=self._get_index_content() if self.index_file.exists() else "",
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
