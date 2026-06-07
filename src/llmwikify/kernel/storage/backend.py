"""Wiki storage backend abstraction.

A WikiBackend is the storage layer for a Wiki: it knows how to read
and write pages, indexes, schema files, logs, and source analysis
caches. The Wiki class itself owns *business logic* (path resolution,
page type mapping, content sanitization, schema merging) and
delegates all raw I/O to a backend.

The default backend is :class:`LocalFileBackend` which stores
everything on the local filesystem. Future backends (in-memory,
remote HTTP, S3) can implement the same :class:`WikiBackend`
protocol and be swapped in without touching the Wiki class or any
of the 13 mixin files.

Design rules:

* The backend is **storage only** — it does not parse content,
  validate page names, or know about Wiki business rules.
* A backend must be safe to use from the Wiki class methods.
  Backends may be backed by a real filesystem, an in-memory dict,
  or a remote service.
* :class:`LocalFileBackend` mirrors the on-disk layout that the
  project has used since v0.1.0; it is the *only* backend shipped
  today and serves as the reference implementation.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ...foundation.config import get_db_path, get_directory, load_config

if TYPE_CHECKING:
    from .index import WikiIndex

logger = logging.getLogger(__name__)


class WikiBackend(Protocol):
    """Storage layer — only data persistence, no business logic.

    The Wiki class orchestrates business logic (path resolution,
    page type mapping, content sanitization) and calls these
    primitives for storage. The concrete implementation (default
    ``LocalFileBackend``, future ``InMemoryBackend``, etc.)
    decides how data is actually stored.

    All methods are storage primitives. None of them perform
    business logic such as name validation, content escaping, or
    page-type resolution — those concerns live in the Wiki class
    and its mixins.
    """

    root: Path
    """Wiki root directory (or virtual root for non-fs backends)."""

    wiki_dir: Path
    """Directory containing wiki pages (index.md, log.md, subdirs)."""

    raw_dir: Path
    """Directory containing raw source files."""

    db_path: Path
    """Path to the SQLite index (use ``Path(':memory:')`` for in-mem)."""

    index: "WikiIndex"
    """SQL-backed (can be :memory: in future) reference index."""

    # === Pages (4 methods) ===
    def get_page(self, name: str) -> str | None: ...
    def put_page(self, name: str, content: str) -> None: ...
    def delete_page(self, name: str) -> bool: ...
    def list_page_paths(self) -> list[Path]: ...

    # === Index (2 methods) ===
    def get_index(self) -> str: ...
    def put_index(self, content: str) -> None: ...

    # === wiki.md (3 methods) ===
    def get_wiki_md(self) -> str | None: ...
    def put_wiki_md(self, content: str) -> None: ...
    def merge_wiki_md(self, existing: str, new: str) -> str: ...

    # === Log (1 method) ===
    def append_log(self, entry: dict[str, Any]) -> dict[str, Any]: ...

    # === Source analysis cache (2 methods) ===
    def get_source_cache(self, key: str) -> dict[str, Any] | None: ...
    def put_source_cache(self, key: str, hash: str, data: dict[str, Any]) -> None: ...

    # === Page type mapping (1 method) ===
    def get_page_type_mapping(self) -> dict[str, str]: ...


class LocalFileBackend:
    """Default backend: filesystem-based storage.

    Encapsulates all the filesystem I/O that used to be inline in
    Wiki methods. ``__init__`` sets up paths and the SQLite index;
    the 13 method implementations are storage primitives only.
    """

    def __init__(self, root: Path, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config(root)
        self.root = root.resolve()
        self.wiki_dir = get_directory(self.root, "wiki", self.config)
        self.raw_dir = get_directory(self.root, "raw", self.config)
        self.db_path = get_db_path(self.root, self.config)
        # Eagerly create the SQLite-backed index. This is cheap
        # (~5ms) and means Wiki never has to worry about lazy
        # initialization. Future InMemoryBackend will pass
        # ``Path(":memory:")`` here for free SQLite in-memory mode.
        from .index import WikiIndex
        self.index: WikiIndex = WikiIndex(self.db_path)

    # === Pages (4 methods) ===
    def get_page(self, name: str) -> str | None:
        path = self._page_path(name)
        if not path.exists():
            return None
        return path.read_text()

    def put_page(self, name: str, content: str) -> None:
        path = self._page_path(name)
        try:
            path.relative_to(self.wiki_dir)
        except ValueError:
            raise ValueError(f"Page path escapes wiki/ directory: {name!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def delete_page(self, name: str) -> bool:
        path = self._page_path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_page_paths(self) -> list[Path]:
        if not self.wiki_dir.exists():
            return []
        return sorted(self.wiki_dir.rglob("*.md"))

    # === Index (2 methods) ===
    def get_index(self) -> str:
        path = self.wiki_dir / "index.md"
        if not path.exists():
            return ""
        return path.read_text()

    def put_index(self, content: str) -> None:
        path = self.wiki_dir / "index.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    # === wiki.md (3 methods) ===
    def get_wiki_md(self) -> str | None:
        path = self.root / "wiki.md"
        if not path.exists():
            return None
        return path.read_text()

    def put_wiki_md(self, content: str) -> None:
        path = self.root / "wiki.md"
        path.write_text(content)

    def merge_wiki_md(self, existing: str, new: str) -> str:
        """Merge new schema sections into existing wiki.md.

        Strategy: simple section collection + dedup notice. Parses
        H2 section headers from both documents (ignoring code
        blocks), collects sections that don't exist in current
        wiki.md, and appends them wrapped in
        ``## Schema Updates (vX.Y.Z)`` with a notice instructing
        the LLM agent to deduplicate.
        """
        existing_sections = _parse_h2_sections(existing)
        new_sections = _parse_h2_sections(new)
        existing_headers = {header.lower() for header, _ in existing_sections}
        sections_to_add = [
            (header, body) for header, body in new_sections
            if header.lower() not in existing_headers
        ]

        version = _get_version_safe()
        if not sections_to_add:
            return re.sub(
                r"Generated by llmwikify v[\d.]+",
                f"Generated by llmwikify v{version}",
                existing,
            )

        new_section_names = [h for h, _ in sections_to_add]
        notice = _build_merge_notice(new_section_names, version)
        new_content = "\n\n".join(
            f"## {header}\n\n{body}" for header, body in sections_to_add
        )

        insert_pos = _find_insertion_point(existing)
        before = existing[:insert_pos]
        after = existing[insert_pos:]
        separator = "\n\n" if not before.endswith("\n\n") else ""
        merged = (
            f"{notice}"
            f"{before}"
            f"{separator}"
            f"## Schema Updates (v{version})\n\n"
            f"{new_content}\n\n"
            f"---\n\n"
            f"{after}"
        )
        return re.sub(
            r"Generated by llmwikify v[\d.]+",
            f"Generated by llmwikify v{version}",
            merged,
        )

    # === Log (1 method) ===
    def append_log(self, entry: dict[str, Any]) -> dict[str, Any]:
        timestamp = entry.get("timestamp") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        operation = entry.get("operation", "")
        details = entry.get("details", "")
        line = f"## [{timestamp}] {operation} | {details}\n"
        log_path = self.wiki_dir / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line)
        return {"timestamp": timestamp, "operation": operation, "details": details, "line": line.strip()}

    # === Source analysis cache (2 methods) ===
    def get_source_cache(self, key: str) -> dict[str, Any] | None:
        path = self._page_path(key)
        if not path.exists():
            return None
        try:
            content = path.read_text()
            match = re.search(r"<!-- llmwikify:analysis (.*?) -->", content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse cached analysis for %s: %s", key, e)
        return None

    def put_source_cache(self, key: str, hash: str, data: dict[str, Any]) -> None:
        path = self._page_path(key)
        if not path.exists():
            logger.debug("Cannot cache analysis; page missing: %s", key)
            return
        try:
            content = path.read_text()
            analysis_json = json.dumps(data, ensure_ascii=False)
            comment = (
                f'<!-- llmwikify:analysis '
                f'{{"version":1,"hash":"{hash}",'
                f'"analyzed_at":"{datetime.now(timezone.utc).isoformat()}",'
                f'"data":{analysis_json}}} -->'
            )
            if "<!-- llmwikify:analysis" in content:
                content = re.sub(r"<!-- llmwikify:analysis.*? -->", comment, content, flags=re.DOTALL)
            else:
                content += f"\n{comment}"
            path.write_text(content)
        except OSError as e:
            logger.warning("Failed to cache source analysis for %s: %s", key, e)

    # === Page type mapping (1 method) ===
    def get_page_type_mapping(self) -> dict[str, str]:
        """Parse wiki.md for the Page Types table.

        Looks for tables like:

        | Type | Location | Purpose |
        |------|----------|---------|
        | Source | wiki/sources/{slug}.md | ... |

        Returns a dict mapping type name → directory name.
        """
        path = self.root / "wiki.md"
        if not path.exists():
            return {}
        content = path.read_text()
        type_to_dir: dict[str, str] = {}
        in_page_types = False
        in_table = False

        for line in content.split("\n"):
            if "## Page Types" in line or "### Custom Page Types" in line:
                in_page_types = True
                in_table = False
                continue
            if in_page_types and line.startswith("## ") and "Page Types" not in line:
                in_page_types = False
                continue
            if not in_page_types:
                continue
            if "|" in line and (line.strip().startswith("|---") or line.strip().startswith("| -")):
                in_table = True
                continue
            if in_table and "|" in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    page_type = parts[0]
                    location = parts[1]
                    match = re.search(r"wiki/([^/\{]+)/", location)
                    if match:
                        directory = match.group(1)
                        type_to_dir[page_type] = directory
        return type_to_dir

    # === Helpers (private) ===
    def _page_path(self, name: str) -> Path:
        """Resolve a page name to a file path under wiki_dir.

        ``name`` is the relative path within ``wiki_dir`` minus the
        ``.md`` suffix (e.g. ``"concepts/Factor Investing"`` or
        ``"index"``).
        """
        return (self.wiki_dir / f"{name}.md").resolve()


# === Module-level helpers (shared between backend and Wiki mixins) ===

def _parse_h2_sections(content: str) -> list[tuple[str, str]]:
    """Parse markdown into list of (section_header, section_body).

    Only H2 headers (``## Header``), ignores code blocks, HTML
    comments, and deeper headers. Returns list of tuples
    ``("Section Name", "section content without header")``.
    """
    sections: list[tuple[str, list[str]]] = []
    current_header: str | None = None
    current_body: list[str] = []
    in_code_block = False
    in_html_comment = False

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            if current_header is not None:
                current_body.append(line)
            continue

        if "<!--" in stripped and "-->" not in stripped:
            in_html_comment = True
        if "-->" in stripped:
            in_html_comment = False
            if current_header is not None:
                current_body.append(line)
            continue

        if in_code_block or in_html_comment:
            if current_header is not None:
                current_body.append(line)
            continue

        if line.startswith("## ") and not line.startswith("### "):
            if current_header is not None:
                sections.append((current_header, "\n".join(current_body).strip()))
            current_header = line[3:].strip()
            current_body = []
        elif current_header is not None:
            current_body.append(line)

    if current_header is not None:
        sections.append((current_header, "\n".join(current_body).strip()))

    return [(header, body) for header, body in sections]


def _find_insertion_point(content: str) -> int:
    """Find position to insert new sections.

    Priority: before ``## Best Practices``, before
    ``## Configuration``, else end of file.
    """
    for marker in ["## Best Practices", "## Configuration"]:
        pos = content.find(marker)
        if pos != -1:
            return pos
    return len(content)


def _build_merge_notice(new_sections: list[str], version: str) -> str:
    """Build the dedup instruction notice for LLM agents."""
    section_list = "\n".join(f"  - {s}" for s in new_sections)
    return (
        f"<!--\n"
        f"  WIKI SCHEMA UPDATE NOTICE\n"
        f"  =========================\n"
        f"  This wiki.md has been updated with new sections from llmwikify v{version}.\n\n"
        f"  NEW SECTIONS ADDED (please review and deduplicate):\n"
        f"{section_list}\n\n"
        f"  ACTION REQUIRED:\n"
        f"  1. Review the \"## Schema Updates (v{version})\" section at the end of this file\n"
        f"  2. If any new sections duplicate existing content, merge them into the existing sections\n"
        f"  3. Remove the \"## Schema Updates\" section after deduplication\n"
        f"  4. Remove this notice after cleanup is complete\n\n"
        f"  The new sections contain updated conventions and workflows that may complement\n"
        f"  or replace your existing customizations.\n"
        f"-->\n\n\n"
    )


def _get_version_safe() -> str:
    try:
        from .. import __version__
        return __version__
    except ImportError:
        return "0.11.0"


__all__ = ["WikiBackend", "LocalFileBackend"]
