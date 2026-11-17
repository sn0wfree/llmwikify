"""Multi-wiki search — the one implementation behind every search entry point.

Layer: L2 (kernel). Shared by the MCP tools
(``interfaces/mcp/tools.py``) and the chat skill actions
(``apps/chat/skills/wiki_query_skill.py``), which must agree on scope
semantics.

Design: ``docs/designs/search-tool-merge.md``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_scope(
    registry: Any,
    *,
    wiki_ids: str | None = None,
    wiki_id: str | None = None,
) -> list[str]:
    """Resolve a search request into the list of wiki ids to hit.

    The deprecated ``wiki_id`` wins over ``wiki_ids`` so old callers keep
    working:

    * ``wiki_id="a"``            -> ``["a"]``
    * ``wiki_ids="a,b"``         -> ``["a", "b"]``
    * ``wiki_ids=None / "" / "*"`` -> every registered wiki

    Raises:
        ValueError: No registered wiki matches the request.
    """
    known = [w.wiki_id for w in registry.list_wikis()]

    if wiki_id:
        targets = [wiki_id]
    elif wiki_ids and wiki_ids.strip() and wiki_ids.strip() != "*":
        targets = [x.strip() for x in wiki_ids.split(",") if x.strip()]
    else:
        targets = list(known)

    valid = [t for t in targets if t in known]
    if not valid:
        raise ValueError(f"Wiki not found: {', '.join(targets)}")
    if len(valid) != len(targets):
        logger.warning("search skipped unknown wikis: %s", targets)
    return valid


def search_wikis(
    registry: Any,
    query: str,
    limit: int = 10,
    *,
    wiki_ids: str | None = None,
    wiki_id: str | None = None,
    backend: str = "fts5",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Search one or more wikis and return ``(results, searched_wiki_ids)``.

    ``limit`` is a GLOBAL cap on the merged result set (not per wiki).
    Every result carries ``wiki_id`` / ``wiki_name`` so callers can tell
    where it came from.

    Args:
        registry: ``WikiRegistry`` instance.
        query: Search query.
        limit: Maximum number of results overall.
        wiki_ids: Comma-separated wiki ids; empty or ``"*"`` = all wikis.
        wiki_id: Deprecated single wiki id; wins over ``wiki_ids``.
        backend: Search backend for local wikis ("fts5" / "qmd"). Remote
            wikis always use their own backend.

    Raises:
        ValueError: Unknown wiki id, or a remote wiki without a client.
    """
    valid = resolve_scope(registry, wiki_ids=wiki_ids, wiki_id=wiki_id)

    if len(valid) == 1:
        wid = valid[0]
        from .instance import WikiType

        instance = registry.get_wiki_instance(wid)
        if instance.wiki_type == WikiType.REMOTE:
            client = registry._remote_clients.get(wid)
            if not client:
                raise ValueError("Remote wiki client not available")
            results = client.search(query, limit)
        else:
            wiki = registry.get_wiki(wid)
            results = wiki.search(query, limit, backend=backend)
        # Tag the origin wiki, so a single-wiki search returns the same
        # shape as a cross-wiki one.
        for r in results:
            r["wiki_id"] = wid
            r["wiki_name"] = instance.name
        return list(results)[:limit], valid

    results = registry.cross_wiki_search(query, valid, limit, backend=backend)
    return list(results)[:limit], valid


__all__ = ["resolve_scope", "search_wikis"]
