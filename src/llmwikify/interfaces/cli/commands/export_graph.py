"""``export_graph`` command — export knowledge graph visualization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._base import Command
from .._output import print_error, print_success


def run_export_graph(wiki: Any, args: Any) -> int:
    """Export the knowledge graph to HTML / SVG / GraphML.

    Args:
        wiki: A Wiki instance (or any object with ``index``).
        args: Parsed argparse Namespace with ``format``, ``output``,
            ``min_degree``.

    Returns:
        0 on success, 1 on failure.
    """
    from llmwikify.core.graph_export import (
        build_graph,
        export_graphml,
        export_html,
        export_svg,
    )

    output = args.output
    fmt = args.format
    if not output:
        ext_map = {"html": ".html", "svg": ".svg", "graphml": ".graphml"}
        output = f"graph{ext_map.get(fmt, '.html')}"

    output_path = Path(output)

    print("=== Exporting Graph ===")
    print(f"Format: {fmt}")
    print(f"Output: {output_path}")

    graph = build_graph(wiki.index)

    try:
        if fmt == "html":
            result = export_html(graph, None, output_path, min_degree=args.min_degree)
        elif fmt == "graphml":
            result = export_graphml(graph, output_path)
        elif fmt == "svg":
            result = export_svg(graph, output_path)
        else:
            print_error(f"Unsupported format: {fmt}")
            return 1

        print()
        print_success(f"Exported: {result['nodes']} nodes, {result['edges']} edges")
        print(f"   Output: {result['output']}")
    except ImportError as e:
        print_error(f"Missing dependency: {e}")
        return 1
    except (RuntimeError, OSError, ValueError) as e:
        print_error(f"Export failed: {e}")
        return 1

    return 0


class ExportGraphCommand(Command):
    """``export_graph`` command — export knowledge graph visualization."""

    name = "export-graph"
    help = "Export knowledge graph visualization"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("--format", choices=["html", "svg", "graphml"], default="html", help="Output format (default: html)")
        p.add_argument("--output", "-o", default=None, help="Output file path")
        p.add_argument("--min-degree", type=int, default=0, help="Filter nodes below this degree")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_export_graph(wiki, args)
