"""Filesystem-safe names for wiki pages (Windows NTFS compatibility).

Logical page names may contain ``:`` (e.g. ``Query: Gold Mining``) and
other punctuation. On Windows, several characters are reserved in a path
component — pathlib/open treat ``:`` as an NTFS Alternate Data Stream,
``?`` is illegal, etc. Without mapping, ``Query: X.md`` silently becomes
a file named ``Query`` and ``glob("*.md")`` misses it.

Policy:
- Linux/macOS (production): identity — existing wikis keep original names.
- Windows: map reserved characters to fullwidth lookalikes on disk;
  reverse mapping restores the logical name for API / index / wikilinks.

Fullwidth forms are reversible and visually close, so disk browsing on
Windows still shows ``Query：Gold Mining.sink.md``.
"""

from __future__ import annotations

import os

# Logical (ASCII/reserved) → filesystem-safe (fullwidth / unicode)
_MAP = {
    ":": "：",  # FULLWIDTH COLON
    "?": "？",  # FULLWIDTH QUESTION MARK
    "*": "＊",  # FULLWIDTH ASTERISK
    '"': "＂",  # FULLWIDTH QUOTATION MARK
    "<": "＜",  # FULLWIDTH LESS-THAN SIGN
    ">": "＞",  # FULLWIDTH GREATER-THAN SIGN
    "|": "｜",  # FULLWIDTH VERTICAL LINE
}
_REV = {v: k for k, v in _MAP.items()}


def _is_windows() -> bool:
    return os.name == "nt"


def to_fs_name(name: str) -> str:
    """Map a logical page/path name to a filesystem-safe name."""
    if not _is_windows():
        return name
    for src, dst in _MAP.items():
        name = name.replace(src, dst)
    return name


def from_fs_name(fs_name: str) -> str:
    """Map a filesystem name back to the logical page name."""
    if not _is_windows():
        return fs_name
    for src, dst in _REV.items():
        fs_name = fs_name.replace(src, dst)
    return fs_name


__all__ = ["to_fs_name", "from_fs_name"]
