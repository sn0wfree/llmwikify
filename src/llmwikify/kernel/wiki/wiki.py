"""Wiki core business logic."""

import logging
from pathlib import Path
from typing import Any

from ...foundation.config import get_db_path, get_directory, load_config
from ..storage.index import WikiIndex
from ..storage.query_sink import QuerySink
from .engines.analyzer import WikiAnalyzer
from ..storage.backend import LocalFileBackend, WikiBackend
from .mixins.io.ingest import WikiIngestMixin
from .mixins.core.init import WikiInitMixin
from .mixins.io.link import WikiLinkMixin
from .mixins.analysis.lint import WikiLintMixin
from .mixins.analysis.llm import WikiLLMMixin
from .mixins.io.page_io import WikiPageIOMixin
from .mixins.analysis.query import WikiQueryMixin
from .mixins.analysis.relation import WikiRelationMixin
from .mixins.core.schema import WikiSchemaMixin
from .mixins.io.source_analysis import WikiSourceAnalysisMixin
from .mixins.analysis.status import WikiStatusMixin
from .mixins.analysis.synthesis import WikiSynthesisMixin
from .mixins.core.utility import WikiUtilityMixin

logger = logging.getLogger(__name__)

VALID_AGENTS = ("opencode", "claude", "codex", "generic")


class Wiki(
    WikiUtilityMixin,
    WikiLinkMixin,
    WikiSchemaMixin,
    WikiInitMixin,
    WikiPageIOMixin,
    WikiSourceAnalysisMixin,
    WikiLLMMixin,
    WikiRelationMixin,
    WikiIngestMixin,
    WikiQueryMixin,
    WikiSynthesisMixin,
    WikiStatusMixin,
    WikiLintMixin,
):
    """Main Wiki manager.

    Storage is delegated to a :class:`WikiBackend` (default
    :class:`LocalFileBackend`). The Wiki class owns *business
    logic* (path resolution, page type mapping, content
    sanitization, schema merging) and calls backend primitives for
    storage. Mixin files should call Wiki helper methods rather
    than ``self._backend`` directly to keep the abstraction
    layered cleanly.

    Inherits functionality from specialized mixins:
    - WikiUtilityMixin: path resolution, slug generation, timestamps, templates
    - WikiLinkMixin: wikilink resolution, fixing, inbound/outbound links
    - WikiSchemaMixin: wiki.md schema reading, updating, page type mapping
    - WikiInitMixin: directory structure, core files, MCP config
    - WikiPageIOMixin: page read/write, search, log, index update
    - WikiSourceAnalysisMixin: source analysis, caching, summary pages
    - WikiLLMMixin: LLM calls with retry, source processing
    - WikiRelationMixin: relation engine, graph analysis, operations
    - WikiIngestMixin: source ingestion, extraction, raw collection
    - WikiQueryMixin: query page creation, similarity matching, sink
    - WikiSynthesisMixin: cross-source synthesis suggestions
    - WikiStatusMixin: status reporting, recommendations, hints
    - WikiLintMixin: health check, lint detection (delegates to WikiAnalyzer)
    """

    def __init__(
        self,
        root: Path,
        config: dict[str, Any] | None = None,
        backend: WikiBackend | None = None,
    ) -> None:
        self.config = config or load_config(root)
        self._backend: WikiBackend = backend or LocalFileBackend(root, self.config)

        # Backward-compat storage attribute aliases (100+ tests
        # and external code read these directly).
        self.root = self._backend.root
        self.wiki_dir = self._backend.wiki_dir
        self.raw_dir = self._backend.raw_dir
        self.db_path = self._backend.db_path
        self.index: WikiIndex = self._backend.index
        self._index = self._backend.index
        self.index_file = self.wiki_dir / "index.md"
        self.log_file = self.wiki_dir / "log.md"
        self.wiki_md_file = self.root / "wiki.md"
        self.sink_dir = self.wiki_dir / ".sink"

        # Special page names (from filenames, used for exclusion logic)
        self._index_page_name = "index"
        self._log_page_name = "log"

        # Reference index path
        ref_index_name = self.config.get("reference_index", {}).get("name", "reference_index.json")
        self._ref_index_path: Path | None = None
        self._ref_index_name = ref_index_name

        # Orphan detection configuration
        orphan_config = self.config.get("orphan_detection", {})
        self._default_exclude_patterns = orphan_config.get("default_exclude_patterns", [])
        self._user_exclude_patterns = orphan_config.get("exclude_patterns", [])
        self._exclude_frontmatter_keys = orphan_config.get("exclude_frontmatter", [])
        self._archive_dirs = orphan_config.get("archive_directories", [])

        # Performance settings
        perf_config = self.config.get("performance", {})
        self._batch_size = perf_config.get("batch_size", 100)

        self._query_sink: QuerySink | None = None

        # Phase 2 #4 — cache the analyzer instance on the Wiki
        # so that lint / recommend / hint / detect_X / _llm_*
        # mixin methods share one WikiAnalyzer (and its
        # LintEngine) instead of re-instantiating per call.
        self._analyzer: WikiAnalyzer = WikiAnalyzer(self)

        # Prompt custom directory (optional, from config)
        prompts_config = self.config.get("prompts", {})
        custom_dir = prompts_config.get("custom_dir")
        self._prompt_custom_dir: Path | None = None
        if custom_dir:
            self._prompt_custom_dir = (self.root / custom_dir).resolve()

    @property
    def ref_index_path(self) -> Path:
        """Path to reference index JSON."""
        if self._ref_index_path is None:
            self._ref_index_path = self.wiki_dir / self._ref_index_name
        return self._ref_index_path

    @property
    def query_sink(self) -> QuerySink:
        """Lazy-load QuerySink."""
        if self._query_sink is None:
            self._query_sink = QuerySink(self.root, self.wiki_dir)
        return self._query_sink

    @property
    def qmd(self) -> Any:
        """Lazy-load QMD hybrid search index (optional feature).

        Returns QmdIndex instance if available, None otherwise.
        """
        try:
            from ..search.qmd_index import QmdIndex
            return QmdIndex(self.root, config=self.config)
        except Exception:
            return None

    def qmd_status(self) -> dict[str, Any]:
        """Get QMD hybrid search engine status and recommendation info.

        Returns:
            Dict with availability, recommendation, and config info
        """
        qmd = self.qmd
        page_count = self.index.get_page_count()

        result = {
            "available": False,
            "recommended": False,
            "page_count": page_count,
            "backend": self.config.get("search", {}).get("backend", "fts5"),
        }

        if qmd is not None:
            result["available"] = qmd.is_available()
            recommendation = qmd.get_recommendation(page_count)
            result["recommended"] = recommendation.get("recommended", False)
            result["threshold"] = recommendation.get("threshold", 1000)
            result["message"] = recommendation.get("message", "")

        return result

    def close(self) -> None:
        """Close database connections."""
        if self._index:
            self._index.close()

    # === Backend helpers (used by mixin files) ===
    # Mixins call these rather than self._backend directly to
    # keep the abstraction layered (mixin → Wiki → backend → fs).

    def _get_wiki_md_content(self) -> str:
        """Read wiki.md content (empty string if missing)."""
        return self._backend.get_wiki_md() or ""

    def _write_wiki_md_content(self, content: str) -> None:
        """Write wiki.md content."""
        self._backend.put_wiki_md(content)

    def _merge_wiki_md_content(self, existing: str, new: str) -> str:
        """Merge new schema into existing wiki.md content."""
        return self._backend.merge_wiki_md(existing, new)

    def _get_index_content(self) -> str:
        """Read index.md content (empty string if missing)."""
        return self._backend.get_index()

    def _write_index_content(self, content: str) -> None:
        """Write index.md content."""
        self._backend.put_index(content)

    def _get_log_content(self) -> str:
        """Read log.md content (empty string if missing)."""
        log_path = self.wiki_dir / "log.md"
        if not log_path.exists():
            return ""
        return log_path.read_text()

    def _ensure_raw_dir(self) -> None:
        """Create raw/ directory if missing."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _find_wiki_page_path(self, name: str) -> Path | None:
        """Find a wiki page by its stem name. Returns Path or None.

        Returns the unique match if exactly one page with the
        given stem exists, ``None`` if zero matches, or the
        shortest-path match if multiple pages share the stem
        (ambiguous — caller should treat with care).

        Unlike ``self._backend.get_page``, this scans the wiki
        tree to find a page by its base name (no directory
        prefix). Used by the link mixin to disambiguate bare
        wikilinks like ``[[Factor Investing]]``.
        """
        matches = self._find_wiki_page_paths(name)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return sorted(matches, key=lambda p: len(p.parts))[0]

    def _find_wiki_page_paths(self, name: str) -> list[Path]:
        """Find all wiki pages with a given stem name.

        Returns a list of Paths (possibly empty) for callers that
        need to disambiguate between multiple matches.
        """
        if not self.wiki_dir.exists():
            return []
        return list(self.wiki_dir.rglob(f"{name}.md"))

    def _get_page_type_mapping(self) -> dict[str, str]:
        """Read page type → directory mapping from wiki.md."""
        return self._backend.get_page_type_mapping()

    def _get_source_cache(self, key: str) -> dict[str, Any] | None:
        """Read cached source analysis by page key (relative path, no .md)."""
        return self._backend.get_source_cache(key)
