"""``community_detect`` command — detect knowledge communities."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command


def run_community_detect(wiki: Any, args: Any) -> int:
    """Detect knowledge communities via Leiden / Louvain.

    Args:
        wiki: A Wiki instance (or any object with ``index``).
        args: Parsed argparse Namespace with ``algorithm``, ``resolution``,
            optional ``json`` and ``dry_run``.

    Returns:
        0 on success.
    """
    from llmwikify.core.graph_export import detect_communities

    result = detect_communities(
        wiki.index,
        algorithm=args.algorithm,
        resolution=args.resolution,
    )

    if "warning" in result:
        print(f"⚠️  {result['warning']}")

    if args.json:
        output = {
            "communities": {str(k): v for k, v in result.get("communities", {}).items()},
            "num_communities": result["num_communities"],
            "modularity": result["modularity"],
            "total_nodes": result["total_nodes"],
            "total_edges": result["total_edges"],
        }
        print(json.dumps(output, indent=2))
        return 0

    if args.dry_run:
        print("=== Community Detection (Dry Run) ===")
        print(f"Algorithm: {args.algorithm}")
        print(f"Resolution: {args.resolution}")
        print(f"Nodes: {result['total_nodes']}")
        print(f"Edges: {result['total_edges']}")
        print(f"Communities: {result['num_communities']}")
        print(f"Modularity: {result['modularity']}")
        return 0

    print("=== Community Detection ===\n")
    print(f"Algorithm: {args.algorithm}")
    print(f"Resolution: {args.resolution}")
    print(f"Total nodes: {result['total_nodes']}")
    print(f"Total edges: {result['total_edges']}")
    print(f"Communities: {result['num_communities']}")
    print(f"Modularity: {result['modularity']} (0-1, higher = clearer separation)")
    print()

    communities = result.get("communities", {})
    for cid, nodes in sorted(communities.items()):
        print(f"Community {cid} ({len(nodes)} nodes):")
        for node in sorted(nodes)[:10]:
            print(f"  - {node}")
        if len(nodes) > 10:
            print(f"  ... and {len(nodes) - 10} more")
        print()

    return 0


class CommunityDetectCommand(Command):
    """``community_detect`` command — detect knowledge communities."""

    name = "community-detect"
    help = "Detect knowledge communities"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--algorithm", choices=["leiden", "louvain"], default="leiden",
            help="Detection algorithm (default: leiden)",
        )
        p.add_argument("--resolution", type=float, default=1.0, help="Resolution parameter (default: 1.0)")
        p.add_argument("--json", action="store_true", help="Output as JSON")
        p.add_argument("--dry-run", "-n", action="store_true", help="Only print stats")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_community_detect(wiki, args)
