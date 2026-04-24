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
    config: dict
    query_sink: Any
    _prompt_custom_dir: str

    # Configuration
    _default_exclude_patterns: list
    _user_exclude_patterns: list
    _exclude_frontmatter_keys: list
    _archive_dirs: set
    _batch_size: int
    _server_config: dict

    # Methods - Utility
    @staticmethod
    def _slugify(text: str) -> str: ...

    @staticmethod
    def _now() -> str: ...

    @staticmethod
    def _get_version() -> str: ...

    @staticmethod
    def _detect_file_type(filename: str) -> str: ...

    @staticmethod
    def _render_template(name: str, **variables: Any) -> str: ...

    # Methods - File operations
    def _get_prompt_registry(self) -> Any: ...

    def _wiki_pages(self) -> Any: ...

    def _page_display_name(self, path: Path) -> str: ...

    def _parse_wikilink_target(self, link: str) -> str: ...

    def _update_index_file(self) -> None: ...

    def _resolve_wikilink_target(self, target: str) -> Path | None: ...

    def _load_page_type_mapping(self) -> dict[str, str]: ...

    def _get_cached_source_analysis(self, source_name: str) -> dict | None: ...

    def _parse_sections(self, content: str) -> dict[str, str]: ...

    def _find_insertion_point(self, existing_sections: list[str], new_section: str) -> int: ...

    def _build_merge_notice(self, new_content: str, existing_content: str) -> str: ...

    # Methods - Core operations
    def append_log(self, operation: str, details: str) -> dict: ...

    def write_page(self, name: str, content: str, page_type: str | None = None) -> dict: ...

    def get_relation_engine(self) -> RelationEngine: ...

    def analyze_source(self, source_path: str, force: bool = False) -> dict: ...

    def is_initialized(self) -> bool: ...

    # Path operations
    @staticmethod
    def join(*parts: str) -> str: ...

    @staticmethod
    def copy(text: str) -> None: ...

    @staticmethod
    def lower(text: str) -> str: ...

    def append(self, text: str) -> None: ...

    def get(self, key: str, default: Any = None) -> Any: ...

    def stop(self) -> None: ...
