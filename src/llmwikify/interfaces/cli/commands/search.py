"""``search`` command — full-text search."""

from __future__ import annotations

import logging
from typing import Any

from .._base import Command

logger = logging.getLogger(__name__)


def run_search(wiki: Any, args: Any) -> int:
    """Search the wiki and print results.

    Args:
        wiki: A Wiki instance (or any object with ``search(query, limit, backend=...)``).
        args: Parsed argparse Namespace with ``query``, ``limit``, ``backend``.

    Returns:
        0 always.
    """
    backend = getattr(args, "backend", "fts5")
    results = wiki.search(
        args.query, getattr(args, "limit", 10), backend=backend
    )

    if not results:
        print(f"No results found for: {args.query}")
        return 0

    print(f"Search results for: {args.query}")
    mode = results[0].get("mode", "fts5") if results else "fts5"
    print(f"Using backend: {mode}")
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['page_name']}")
        print(f"   Score: {r['score']}")
        print(f"   {r['snippet']}")

    return 0


class SearchCommand(Command):
    """``search`` command — full-text search."""

    name = "search"
    help = "Full-text search"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("query", help="Search query")
        p.add_argument("--limit", "-l", type=int, default=10)
        p.add_argument(
            "--backend", "-b",
            choices=["fts5", "qmd"],
            default="fts5",
            help="Search backend: fts5 (default, fast) or qmd (hybrid semantic)",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_search(wiki, args)
