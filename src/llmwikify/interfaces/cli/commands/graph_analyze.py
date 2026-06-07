"""``graph_analyze`` command — analyze knowledge graph structure."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command


def run_graph_analyze(wiki: Any, args: Any) -> int:
    """Analyze the knowledge graph structure (PageRank, communities, suggestions).

    Args:
        wiki: A Wiki instance (or any object with ``graph_analyze()``
            and ``graph_suggested_pages_report()``).
        args: Parsed argparse Namespace with optional ``json`` and ``report``.

    Returns:
        0 on success.
    """
    as_json = getattr(args, "json", False)
    detailed_report = getattr(args, "report", False)

    if detailed_report:
        report = wiki.graph_suggested_pages_report()
        print(report)
        return 0

    result = wiki.graph_analyze()

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if result.get("status") == "empty":
        print(result.get("message", "No graph data available"))
        return 0

    print("=== Knowledge Graph Analysis ===\n")

    # Stats
    stats = result.get("stats", {})
    print(f"Nodes: {stats.get('nodes', 0)}")
    print(f"Edges: {stats.get('edges', 0)}")
    print(f"Density: {stats.get('density', 0)}")
    print(f"Connected: {'Yes' if stats.get('is_connected') else 'No'}")

    # Centrality
    centrality = result.get("centrality", {})
    if centrality.get("pagerank"):
        print("\n=== Core Concepts (PageRank) ===")
        for item in centrality["pagerank"][:5]:
            print(f"  • {item['node']} (score: {item['score']})")

    if centrality.get("hubs"):
        print("\n=== Hub Nodes (high out-degree) ===")
        for item in centrality["hubs"][:5]:
            print(f"  • {item['node']} (out-degree: {item['out_degree']})")

    if centrality.get("authorities"):
        print("\n=== Authority Nodes (high in-degree) ===")
        for item in centrality["authorities"][:5]:
            print(f"  • {item['node']} (in-degree: {item['in_degree']})")

    # Communities
    communities = result.get("communities", {})
    if communities.get("communities"):
        print(f"\n=== Communities ({communities.get('num_communities', 0)}) ===")
        for comm in list(communities["communities"].values())[:5]:
            print(f"  • {comm['label']}: {comm['size']} nodes")

        if communities.get("bridges"):
            print("\n=== Bridge Nodes ===")
            for bridge in communities["bridges"][:5]:
                print(f"  • {bridge['node']}: {bridge['observation']}")

    # Suggestions
    suggestions = result.get("suggestions", [])
    if suggestions:
        print(f"\n=== Suggested Pages ({len(suggestions)}) ===")
        for sugg in suggestions[:10]:
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                sugg.get("priority"), "•"
            )
            print(f"  {priority_icon} [{sugg.get('priority', 'info').upper()}] {sugg['observation']}")
            print(f"     → {sugg['suggestion']}")
    else:
        print("\n✅ No suggestions at this time")

    print()
    return 0


class GraphAnalyzeCommand(Command):
    """``graph_analyze`` command — analyze knowledge graph structure."""

    name = "graph-analyze"
    help = "Analyze knowledge graph structure (PageRank, communities, suggestions)"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("--json", action="store_true", help="Output as JSON")
        p.add_argument("--report", action="store_true", help="Generate detailed suggested pages report")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_graph_analyze(wiki, args)
