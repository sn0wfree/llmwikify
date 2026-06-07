"""Common file/cache/serialization utilities (L1: foundation).

Per the 4-layer refactor (Batch B1), this module is the home
for shared I/O patterns extracted from across the codebase
(query_sink, graph_analyzer, wiki_backend, etc.).

Initial version is a placeholder. Concrete utilities will be
added as they are identified during subsequent batches.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON from path, returning default if file doesn't exist.

    Args:
        path: Path to JSON file.
        default: Value to return if file doesn't exist or is invalid.

    Returns:
        Parsed JSON value, or default.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write data as JSON to path, creating parent dirs as needed.

    Args:
        path: Destination path.
        data: JSON-serializable data.
        indent: JSON indentation level.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")


def safe_read_text(path: Path, default: str = "") -> str:
    """Read text from path, returning default if file doesn't exist.

    Args:
        path: Path to text file.
        default: Value to return if file doesn't exist.

    Returns:
        File contents, or default.
    """
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def safe_write_text(path: Path, content: str) -> None:
    """Write text to path, creating parent dirs as needed.

    Args:
        path: Destination path.
        content: Text content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
