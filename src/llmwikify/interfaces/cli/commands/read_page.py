"""``read_page`` command — read a wiki page to stdout."""

from __future__ import annotations

import logging
from typing import Any

from .._base import CommandBase
from .._output import print_error

logger = logging.getLogger(__name__)


def run_read_page(wiki: Any, args: Any) -> int:
    """Read a wiki page and print its content.

    Args:
        wiki: A Wiki instance (or any object with ``read_page(name, page_type=...)``).
        args: Parsed argparse Namespace with ``name`` and optional ``type``.

    Returns:
        0 on success, 1 on error.
    """
    page_type = getattr(args, "type", None)
    result = wiki.read_page(args.name, page_type=page_type)

    if "error" in result:
        print_error(result["error"])
        return 1

    print(result["content"])
    return 0


class ReadPageCommand(CommandBase):
    """``read_page`` command — read a wiki page."""

    name = "read_page"
    help = "Read page"

    def setup_parser(self, subparsers: Any) -> None:
        p = self._sub(subparsers)
        p.add_argument("name", help="Page name")
        p.add_argument("--type", "-t", help="Page type from wiki.md Page Types table")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_read_page(wiki, args)
