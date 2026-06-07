"""``write_page`` command — write a wiki page."""

from __future__ import annotations

import sys
from typing import Any

from .._base import Command
from .._output import print_error, print_success


def run_write_page(wiki: Any, args: Any) -> int:
    """Write a wiki page.

    Args:
        wiki: A Wiki instance (or any object with
            ``write_page(name, content, page_type=...)``).
        args: Parsed argparse Namespace with ``name``, optional
            ``type``, ``file``, ``content``.

    Returns:
        0 on success, 1 on missing content.
    """
    content = _get_content(args)
    if not content:
        print_error("Error: No content provided")
        return 1

    page_type = getattr(args, "type", None)
    result = wiki.write_page(args.name, content, page_type=page_type)
    print_success(str(result))
    return 0


def _get_content(args: Any) -> str | None:
    """Get content from --file, --content, or stdin.

    Preserved from WikiCLI._get_content. The order is:
    1. ``args.file`` (read from filesystem)
    2. ``args.content`` (literal string)
    3. stdin
    """
    if getattr(args, "file", None):
        try:
            with open(args.file) as f:
                return f.read()
        except OSError as e:
            print_error(f"Error reading file: {e}")
            return None
    elif getattr(args, "content", None):
        return str(args.content)
    else:
        return sys.stdin.read()


class WritePageCommand(Command):
    """``write_page`` command — write a wiki page."""

    name = "write_page"
    help = "Write page"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("name", help="Page name")
        p.add_argument(
            "--type", "-t",
            help="Page type from wiki.md Page Types table (e.g., concept, model, source)",
        )
        p.add_argument("--file", "-f", help="Read content from file")
        p.add_argument("--content", "-c", help="Content as string")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_write_page(wiki, args)
