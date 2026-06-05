"""``status`` command — show wiki status."""

from __future__ import annotations

from typing import Any

from .._base import Command
from .._output import ICON_INFO, ICON_SEARCH, ICON_CLIPBOARD, print_error


def run_status(wiki: Any, args: Any) -> int:
    """Print wiki status. Returns 0 if initialized, 1 if not.

    Args:
        wiki: A Wiki instance (or any object with ``status()``).
        args: Parsed argparse Namespace (currently unused).
    """
    result = wiki.status()

    if not result.get("initialized"):
        print_error("Wiki not initialized")
        return 1

    print("=== Wiki Status ===")
    print(f"Root: {result['root']}")
    print(f"Pages: {result['page_count']}")
    print(f"Sources: {result['source_count']}")
    print(f"Indexed: {result.get('indexed_pages', 'N/A')}")
    print(f"Links: {result.get('total_links', 'N/A')}")

    return 0


class StatusCommand(Command):
    """``status`` command — show wiki status."""

    name = "status"
    help = "Show status"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        subparsers.add_parser(self.name, help=self.help)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_status(wiki, args)
