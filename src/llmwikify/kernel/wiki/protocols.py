"""Protocol definitions for mixin type resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engines.relation import RelationEngine


class WikiProtocol:
    """Protocol defining attributes and methods available to all mixins.

    This class helps mypy resolve cross-mixin attribute references without
    runtime overhead. It should be inherited by all mixin classes.
    """

    # Core paths
    root: Path
    wiki_dir: Path
    raw_dir: Path
    db_path: Path
    index_file: Path
    ref_index_path: Path
    wiki_md_file: Path
    log_file: Path
    sink_dir: Path
    _index_page_name: str
    _log_page_name: str

    # Core objects
    index: Any
    config: dict[str, Any]
    query_sink: Any
    _analyzer: Any
    _backend: Any
    _prompt_custom_dir: Path | None

    # Configuration
    _default_exclude_patterns: list[str]
    _user_exclude_patterns: list[str]
    _exclude_frontmatter_keys: list[str]
    _archive_dirs: set[str]
    _batch_size: int
    _server_config: dict[str, Any]

    # Methods - Utility
    @staticmethod
    def _slugify(text: str) -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def _now() -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def _get_version() -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def _detect_file_type(filename: str) -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def _render_template(name: str, **variables: Any) -> str: ...  # type: ignore[empty-body]

    # Methods - File operations
    def _get_prompt_registry(self) -> Any: ...

    def _wiki_pages(self) -> Any: ...

    def _page_display_name(self, path: Path) -> str: ...  # type: ignore[empty-body]

    def _parse_wikilink_target(self, link: str) -> str: ...  # type: ignore[empty-body]

    def _update_index_file(self) -> None: ...

    def _resolve_wikilink_target(self, target: str) -> Path | None: ...

    def _load_page_type_mapping(self) -> dict[str, str]: ...  # type: ignore[empty-body]

    def _get_cached_source_analysis(self, page_path: Path) -> dict[str, Any] | None: ...

    # Methods - Utility (implemented in mixins/core/utility.py)
    @staticmethod
    def _parse_sections(content: str) -> list[tuple[str, str]]: ...  # type: ignore[empty-body]

    @staticmethod
    def _find_insertion_point(content: str) -> int: ...  # type: ignore[empty-body]

    @staticmethod
    def _build_merge_notice(new_sections: list[str], version: str) -> str: ...  # type: ignore[empty-body]

    # Index content (implemented in wiki.py, used by core/utility mixin)
    def _get_index_content(self) -> str: ...  # type: ignore[empty-body]

    def _write_index_content(self, content: str) -> None: ...

    # Cross-mixin methods (implemented in io/ingest + analysis mixins)
    def extract_section_metadata(self, content: str, title: str = "") -> dict: ...  # type: ignore[empty-body]

    def targeted_read(  # type: ignore[empty-body]
        self, content: str, selected_sections: list[int], max_chars: int = 32000
    ) -> tuple[str, bool]: ...

    def _select_sections(  # type: ignore[empty-body]
        self, section_metadata: dict, content_type: str = "unknown"
    ) -> dict: ...

    def _get_source_cache(self, key: str) -> dict[str, Any] | None: ...

    # Methods - wiki.md schema (implemented in wiki.py, used by core/init mixin)
    def _get_wiki_md_content(self) -> str: ...  # type: ignore[empty-body]

    def _write_wiki_md_content(self, content: str) -> None: ...

    def _merge_wiki_md_content(self, existing: str, new: str) -> str: ...  # type: ignore[empty-body]

    # Methods - Core operations
    def append_log(self, operation: str, details: str) -> str: ...  # type: ignore[empty-body]

    def write_page(self, name: str, content: str, page_type: str | None = None) -> str: ...  # type: ignore[empty-body]

    def get_relation_engine(self) -> RelationEngine: ...  # type: ignore[empty-body]

    def analyze_source(self, source_path: str, force: bool = False) -> dict[str, Any]: ...  # type: ignore[empty-body]

    def is_initialized(self) -> bool: ...  # type: ignore[empty-body]

    # Layout introspection (v0.40+ — for `llmwikify doctor`).
    @property
    def expected_layout(self) -> dict[str, Path]: ...  # type: ignore[empty-body]

    @property
    def actual_layout(self) -> dict[str, Path]: ...  # type: ignore[empty-body]

    def check_layout(self) -> dict[str, bool]: ...  # type: ignore[empty-body]

    def layout_diff(self) -> dict[str, list[str]]: ...  # type: ignore[empty-body]

    def _extract_subdirs_from_wiki_md(self) -> list[str]: ...  # type: ignore[empty-body]

    # Path operations
    @staticmethod
    def join(*parts: str) -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def copy(text: str) -> None: ...

    @staticmethod
    def lower(text: str) -> str: ...  # type: ignore[empty-body]

    def append(self, text: str) -> None: ...

    def get(self, key: str, default: Any = None) -> Any: ...

    def stop(self) -> None: ...
