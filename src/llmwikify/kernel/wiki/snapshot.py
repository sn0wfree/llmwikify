"""Immutable snapshot of the wiki pages, read once per lint run.

A lint run reads every wiki page several times: the analyzer scan reads
them, then each rule reads them again. ``PageSnapshot`` holds the page
contents once so that all consumers of one lint run can share them.

The snapshot is a *cache*, never a filter: a page that does not fit into
the memory budget is not dropped, it is listed in ``omitted`` and the
consumer falls back to reading that page from disk. The set of checked
pages therefore stays exactly the same, only the memory is bounded.

The object is immutable (``frozen`` dataclass + ``MappingProxyType``) so
it can be shared between threads without a lock.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Type only: importing ``Wiki`` at runtime would close the cycle
    # wiki -> analyzer -> lint -> snapshot -> wiki.
    from .wiki import Wiki

logger = logging.getLogger(__name__)

# -- memory budget (basis: design section 6, recon C17) ----------------
SNAPSHOT_MAX_PAGE_BYTES = 1 * 1024 * 1024  # 1 MiB per page
SNAPSHOT_MAX_TOTAL_BYTES = 64 * 1024 * 1024  # 64 MiB per snapshot


@dataclass(frozen=True)
class PageSnapshot:
    """The page contents of one lint run, read once.

    The key is the **display name** (``wiki._page_display_name``: the
    posix relative path without ``.md``). It is injective for different
    relative paths (recon C13), so it is safe to use as a key.

    Invariants
    ---------
    * ``names`` / ``paths`` / ``relative_names`` cover **every** page of
      ``wiki._wiki_pages()``, in that order;
    * ``contents`` is a **subset** of ``names``: only the pages that fit
      into the memory budget carry their content, the other ones are
      listed in ``omitted``;
    * the snapshot performs **no page name filtering** (no ``Query:``
      filter): which pages are skipped is platform dependent (recon
      C11), so the filter stays with the consumers.
    """

    names: tuple[str, ...]
    contents: Mapping[str, str]
    paths: Mapping[str, Path]
    relative_names: tuple[str, ...]
    omitted: tuple[str, ...] = ()
    byte_size: int = 0

    def __post_init__(self) -> None:
        # A frozen dataclass only freezes the attributes; the mappings
        # are wrapped as well, so the snapshot is deeply read-only.
        object.__setattr__(self, "contents", MappingProxyType(dict(self.contents)))
        object.__setattr__(self, "paths", MappingProxyType(dict(self.paths)))

    def content_of(self, name: str) -> str | None:
        """Return the content of a page, or None when it was not cached."""
        return self.contents.get(name)

    def path_of(self, name: str) -> Path:
        """Return the path of a page."""
        return self.paths[name]

    @property
    def degraded(self) -> bool:
        """True when pages were left out because of the memory budget."""
        return bool(self.omitted)


class PageSource(Protocol):
    """Provides the page snapshot of a wiki.

    The implementation decides how the pages are enumerated and read.
    """

    def snapshot(self) -> PageSnapshot: ...


@dataclass(frozen=True, eq=False)
class WikiPageSource:
    """Default :class:`PageSource`: reads the pages of a wiki once.

    The enumeration **must** reuse ``wiki._wiki_pages()`` (recon C12):
    ``is_path_excluded`` judges every segment of the *absolute* path, so
    the set of pages depends on the absolute path of the wiki root --
    enumerating the pages somewhere else yields a different set.
    """

    wiki: Wiki
    max_total_bytes: int = SNAPSHOT_MAX_TOTAL_BYTES
    max_page_bytes: int = SNAPSHOT_MAX_PAGE_BYTES

    def snapshot(self) -> PageSnapshot:
        """Read the pages of the wiki into an immutable snapshot."""
        pages = self.wiki._wiki_pages()
        budget = min(self.max_total_bytes, len(pages) * self.max_page_bytes)

        names: list[str] = []
        relative_names: list[str] = []
        paths: dict[str, Path] = {}
        contents: dict[str, str] = {}
        omitted: list[str] = []
        used = 0

        for page in pages:
            name = self.wiki._page_display_name(page)
            if name in paths:
                # Cannot happen for different relative paths (recon C13),
                # but a case insensitive file system could produce it.
                logger.warning(
                    "lint page snapshot: duplicate page name %r, keeping the first one",
                    name,
                )
                continue
            names.append(name)
            paths[name] = page
            relative_names.append(str(page.relative_to(self.wiki.wiki_dir)))

            try:
                size = page.stat().st_size
            except OSError:
                # The page cannot be measured: do not cache it. The
                # consumer reads it back and fails the same way it would
                # fail today.
                omitted.append(name)
                continue
            if size > self.max_page_bytes or used + size > budget:
                # Too big for the budget: the page is not cached, but it
                # is kept in the snapshot so that the consumer can read
                # it back -- the checked pages do not change.
                omitted.append(name)
                continue
            try:
                content = page.read_text(encoding="utf-8", errors="replace")
            except OSError:
                omitted.append(name)
                continue
            contents[name] = content
            used += size

        snapshot = PageSnapshot(
            names=tuple(names),
            contents=contents,
            paths=paths,
            relative_names=tuple(relative_names),
            omitted=tuple(omitted),
            byte_size=used,
        )
        if snapshot.degraded:
            logger.warning(
                "lint page snapshot degraded: %d/%d pages not cached, "
                "%d bytes used of %d budget",
                len(omitted),
                len(pages),
                used,
                budget,
            )
        return snapshot
