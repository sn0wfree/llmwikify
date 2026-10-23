"""Shared fingerprint cache for graph endpoints.

Fingerprint (pages|page_links|relations count+max rowid) is the real
invalidation signal; TTL is a safety net. Used by:
- GraphAnalyzer.analyze (expensive PageRank / communities)
- build_visualization_data (HTTP /api/wiki/graph)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
# (kind, wiki_key, extra) -> (fingerprint, value, stored_at_monotonic)
_STORE: dict[tuple[str, str, str], tuple[str, Any, float]] = {}

# Analyze is expensive; viz is cheap to recompute but we still avoid
# full rebuild on UI refresh. User asked for 60s on the shared graph path.
TTL_VIZ_S = 60.0
TTL_ANALYZE_S = 3600.0


def graph_fingerprint(conn: Any) -> str:
    """Cheap content fingerprint: any page/link/relation change bumps it."""
    if conn is None:
        return "no-index"

    def _count_max(table: str) -> tuple[int, int]:
        try:
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM {table}"
            ).fetchone()
            return int(row[0]), int(row[1])
        except sqlite3.Error:
            return 0, 0

    pages = _count_max("pages")
    links = _count_max("page_links")
    rels = _count_max("relations")
    return f"{pages[0]}:{pages[1]}|{links[0]}:{links[1]}|{rels[0]}:{rels[1]}"


def file_fingerprint(wiki_dir: Any) -> str:
    """mtime+size fingerprint for on-disk pages (catches in-place edits).

    Combined with :func:`graph_fingerprint` so rowid-stable DB updates
    and direct md edits both invalidate.
    """
    if wiki_dir is None:
        return "no-dir"
    try:
        from pathlib import Path

        root = Path(wiki_dir)
        if not root.exists():
            return "missing"
    except Exception:
        return "no-dir"

    n = 0
    mt_sum = 0
    sz_sum = 0
    try:
        for p in root.rglob("*.md"):
            try:
                st = p.stat()
            except OSError:
                continue
            n += 1
            mt_sum += int(st.st_mtime)
            sz_sum += st.st_size
    except OSError:
        return "stat-err"
    return f"md:{n}:{mt_sum}:{sz_sum}"


def combined_fingerprint(conn: Any, wiki_dir: Any) -> str:
    return f"{graph_fingerprint(conn)}|{file_fingerprint(wiki_dir)}"


def wiki_cache_key(wiki: Any) -> str:
    return str(getattr(wiki, "root", "") or id(wiki))


def cache_get(
    kind: str,
    wiki_key: str,
    fingerprint: str,
    *,
    extra: str = "",
    ttl_s: float,
) -> Any | None:
    key = (kind, wiki_key, extra)
    now = time.monotonic()
    with _LOCK:
        hit = _STORE.get(key)
        if hit is None:
            return None
        stored_fp, value, ts = hit
        if stored_fp != fingerprint or now - ts > ttl_s:
            _STORE.pop(key, None)
            return None
        return value


def cache_put(
    kind: str,
    wiki_key: str,
    fingerprint: str,
    value: Any,
    *,
    extra: str = "",
) -> None:
    key = (kind, wiki_key, extra)
    with _LOCK:
        _STORE[key] = (fingerprint, value, time.monotonic())


def cache_invalidate(wiki_key: str | None = None) -> None:
    """Drop all entries, or only those for one wiki."""
    with _LOCK:
        if wiki_key is None:
            _STORE.clear()
            return
        for key in [k for k in _STORE if k[1] == wiki_key]:
            _STORE.pop(key, None)
