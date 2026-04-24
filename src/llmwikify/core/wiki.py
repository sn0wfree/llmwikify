"""Wiki core business logic."""

import logging
from pathlib import Path
from typing import Any

from ..config import get_db_path, get_directory, load_config
from .index import WikiIndex
from .query_sink import QuerySink
from .wiki_mixin_ingest import WikiIngestMixin
from .wiki_mixin_init import WikiInitMixin
from .wiki_mixin_link import WikiLinkMixin
from .wiki_mixin_lint import WikiLintMixin
from .wiki_mixin_llm import WikiLLMMixin
from .wiki_mixin_page_io import WikiPageIOMixin
from .wiki_mixin_query import WikiQueryMixin
from .wiki_mixin_relation import WikiRelationMixin
from .wiki_mixin_schema import WikiSchemaMixin
from .wiki_mixin_source_analysis import WikiSourceAnalysisMixin
from .wiki_mixin_status import WikiStatusMixin
from .wiki_mixin_synthesis import WikiSynthesisMixin
from .wiki_mixin_utility import WikiUtilityMixin

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

    def __init__(self, root: Path, config: dict[str, Any] | None = None) -> None:
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

    def close(self) -> None:
        """Close database connections."""
        if self._index:
            self._index.close()
