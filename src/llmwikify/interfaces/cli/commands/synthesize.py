"""``synthesize`` command — save query answer as wiki page."""

from __future__ import annotations

import sys
from typing import Any

from .._base import Command
from .._output import print_error, print_success


def run_synthesize(wiki: Any, args: Any) -> int:
    """Save a query answer as a wiki page.

    Args:
        wiki: A Wiki instance (or any object with
            ``synthesize_query(query, answer, source_pages, raw_sources,
            page_name, auto_link, auto_log, mode)``).
        args: Parsed argparse Namespace.

    Returns:
        0 on success, 1 on missing content or error.
    """
    answer = args.answer
    if not answer:
        answer = sys.stdin.read()

    if not answer:
        print_error("No answer content provided")
        return 1

    result = wiki.synthesize_query(
        query=args.query,
        answer=answer,
        source_pages=args.sources or [],
        raw_sources=getattr(args, "raw_sources", None) or [],
        page_name=args.page_name,
        auto_link=not getattr(args, "no_auto_link", False),
        auto_log=not getattr(args, "no_auto_log", False),
        mode=args.mode,
    )

    if "error" in result:
        print_error(result["error"])
        return 1

    print_success(f"Synthesized: {result.get('page_name', args.query)}")
    return 0


class SynthesizeCommand(Command):
    """``synthesize`` command — save query answer as wiki page."""

    name = "synthesize"
    help = "Save query answer as wiki page"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("query", help="Original question")
        p.add_argument("--answer", "-a", help="Answer content (or read from stdin)")
        p.add_argument("--page-name", "-n", help="Custom page name")
        p.add_argument("--sources", nargs="*", help="Source pages to link")
        p.add_argument("--raw-sources", nargs="*", help="Raw source files to cite")
        p.add_argument(
            "--mode", choices=["sink", "update"], default="sink",
            help="Strategy when similar query exists",
        )
        p.add_argument("--no-auto-link", action="store_true", help="Disable automatic wikilink insertion")
        p.add_argument("--no-auto-log", action="store_true", help="Disable automatic log entry")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_synthesize(wiki, args)
