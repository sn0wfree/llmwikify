"""``report`` command — generate unexpected connections report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._base import Command


def run_report(wiki: Any, args: Any) -> int:
    """Generate an unexpected-connections report.

    Args:
        wiki: A Wiki instance (or any object with ``index``).
        args: Parsed argparse Namespace with ``top``, optional ``output``.

    Returns:
        0 on success.
    """
    from llmwikify.kernel.graph.export import detect_communities, generate_report

    comm_result = detect_communities(wiki.index)
    communities = comm_result.get("communities", {})

    report_text = generate_report(wiki.index, communities, top_n=args.top)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report_text)
        print(f"Report written to: {output_path}")
    else:
        print(report_text)

    return 0


class ReportCommand(Command):
    """``report`` command — generate unexpected connections report."""

    name = "report"
    help = "Generate unexpected connections report"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("--top", type=int, default=10, help="Number of top connections (default: 10)")
        p.add_argument("--output", "-o", default=None, help="Output file path")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_report(wiki, args)
