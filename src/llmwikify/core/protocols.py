"""Protocol definitions for mixin type resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .relation_engine import RelationEngine


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
    _prompt_custom_dir: str

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
    def _get_prompt_registry(self) -> Any: ...  # type: ignore[empty-body]

    def _wiki_pages(self) -> Any: ...  # type: ignore[empty-body]

    def _page_display_name(self, path: Path) -> str: ...  # type: ignore[empty-body]

    def _parse_wikilink_target(self, link: str) -> str: ...  # type: ignore[empty-body]

    def _update_index_file(self) -> None: ...  # type: ignore[empty-body]

    def _resolve_wikilink_target(self, target: str) -> Path | None: ...  # type: ignore[empty-body]

    def _load_page_type_mapping(self) -> dict[str, str]: ...  # type: ignore[empty-body]

    def _get_cached_source_analysis(self, source_name: str) -> dict[str, Any] | None: ...  # type: ignore[empty-body]

    def _parse_sections(self, content: str) -> dict[str, str]: ...  # type: ignore[empty-body]

    def _find_insertion_point(self, existing_sections: list[str], new_section: str) -> int: ...  # type: ignore[empty-body]

    def _build_merge_notice(self, new_content: str, existing_content: str) -> str: ...  # type: ignore[empty-body]

    # Methods - Core operations
    def append_log(self, operation: str, details: str) -> dict[str, Any]: ...  # type: ignore[empty-body]

    def write_page(self, name: str, content: str, page_type: str | None = None) -> dict[str, Any]: ...  # type: ignore[empty-body]

    def get_relation_engine(self) -> RelationEngine: ...  # type: ignore[empty-body]

    def analyze_source(self, source_path: str, force: bool = False) -> dict[str, Any]: ...  # type: ignore[empty-body]

    def is_initialized(self) -> bool: ...  # type: ignore[empty-body]

    # Path operations
    @staticmethod
    def join(*parts: str) -> str: ...  # type: ignore[empty-body]

    @staticmethod
    def copy(text: str) -> None: ...  # type: ignore[empty-body]

    @staticmethod
    def lower(text: str) -> str: ...  # type: ignore[empty-body]

    def append(self, text: str) -> None: ...  # type: ignore[empty-body]

    def get(self, key: str, default: Any = None) -> Any: ...  # type: ignore[empty-body]

    def stop(self) -> None: ...  # type: ignore[empty-body]
