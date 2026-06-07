"""``sink_status`` command — show query sink buffer status."""

from __future__ import annotations

from typing import Any

from .._base import Command


def run_sink_status(wiki: Any, args: Any) -> int:
    """Print the wiki's query sink status. Returns 0 always.

    Args:
        wiki: A Wiki instance (or any object with ``sink_status()``).
        args: Parsed argparse Namespace (currently unused).
    """
    status = wiki.sink_status()
    print(f"Sink status: {status}")
    return 0


class SinkStatusCommand(Command):
    """``sink_status`` command — show query sink buffer status."""

    name = "sink-status"
    help = "Show query sink buffer status"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        subparsers.add_parser(self.name, help=self.help)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_sink_status(wiki, args)
