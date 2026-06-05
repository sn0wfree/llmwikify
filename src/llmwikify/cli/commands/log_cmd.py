"""``log`` command — record a log entry."""

from __future__ import annotations

from typing import Any

from .._base import Command
from .._output import print_error, print_success


def run_log(wiki: Any, args: Any) -> int:
    """Record a log entry.

    Args:
        wiki: A Wiki instance (or any object with ``append_log(op, desc)``).
        args: Parsed argparse Namespace with either positional
            ``operation``/``description`` or flag ``op_flag``/``details``.

    Returns:
        0 on success, 1 if both operation and description are missing.
    """
    operation = getattr(args, "op_flag", None) or args.operation
    description = getattr(args, "details", None) or args.description

    if not operation or not description:
        print_error("operation and description required")
        print("Usage: llmwikify log <operation> <description>")
        print("   or: llmwikify log --operation <op> --details <desc>")
        return 1

    result = wiki.append_log(operation, description)
    print_success(str(result))
    return 0


class LogCommand(Command):
    """``log`` command — record a log entry."""

    name = "log"
    help = "Record log"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("operation", nargs="?", help="Operation name (positional)")
        p.add_argument("description", nargs="?", help="Description (positional)")
        p.add_argument(
            "--operation", "-o", dest="op_flag",
            help="Operation name (flag)",
        )
        p.add_argument("--details", "-d", help="Description (flag)")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_log(wiki, args)
