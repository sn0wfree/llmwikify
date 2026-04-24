"""Graph visualization utilities for llmwikify.

Shared between MCP tools and REST API handlers.
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.core.graph_export import build_graph


logger = logging.getLogger(__name__)


def build_visualization_data(
    index,
    wiki,
    current_page: str | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """Build knowledge graph data optimized for visualization.

    This is the single source of truth for graph visualization logic.
    Used by both MCP tools and REST API handlers.

    Args:
        index: Wiki index object
        wiki: Wiki instance (for page type mapping)
        current_page: Optional page name to center visualization around
        mode: Display mode - 'auto', 'full', 'focused', or 'minimal'

    Returns:
        Dict with:
            nodes: List of node dicts (id, label, page_type)
            edges: List of edge dicts (source, target)
            stats: Display statistics (total/displayed nodes, mode)
            all_types: List of page type names for coloring
    """
    try:
        graph_data = build_graph(
            index, include_wikilinks=True, include_relations=False
        )
    except Exception as e:
        logger.exception("Failed to build graph")
        return {
            "nodes": [],
            "edges": [],
            "stats": {
                "total_nodes": 0,
                "displayed_nodes": 0,
                "mode": "empty",
            },
            "all_types": [],
        }

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    total_nodes = len(nodes)

    # Determine display strategy based on wiki size
    if total_nodes < 50 or mode == "full":
        display_nodes = nodes
        display_edges = edges
        display_mode = "full"
    elif total_nodes < 200 or mode == "focused":
        if current_page:
            neighbors = set()
            neighbors.add(current_page)
            for e in edges:
                if e["source"] == current_page:
                    neighbors.add(e["target"])
                if e["target"] == current_page:
                    neighbors.add(e["source"])
            # Add hub nodes (high degree nodes)
            degree_count = {}
            for e in edges:
                degree_count[e["source"]] = degree_count.get(e["source"], 0) + 1
                degree_count[e["target"]] = degree_count.get(e["target"], 0) + 1
            hubs = sorted(degree_count.keys(), key=lambda x: -degree_count[x])[:10]
            for h in hubs:
                neighbors.add(h)
            display_nodes = [n for n in nodes if n["id"] in neighbors]
        else:
            display_nodes = nodes[:50]
        display_mode = "focused"
    else:
        # Large wiki: only current page + 1-degree neighbors
        if current_page:
            neighbors = set()
            neighbors.add(current_page)
            for e in edges:
                if e["source"] == current_page:
                    neighbors.add(e["target"])
                if e["target"] == current_page:
                    neighbors.add(e["source"])
            display_nodes = [n for n in nodes if n["id"] in neighbors]
        else:
            display_nodes = nodes[:30]
        display_mode = "minimal"

    # Filter edges for display nodes
    node_ids = {n["id"] for n in display_nodes}
    display_edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

    # Load page type mapping for coloring
    try:
        type_map = wiki._load_page_type_mapping()
    except Exception:
        type_map = {}

    # Build result nodes with type info
    result_nodes = []
    for n in display_nodes:
        nid = n["id"]
        page_type = n.get("source_type", "wiki_page")
        for type_name, type_dir in type_map.items():
            if nid.startswith(type_dir + "/") or nid == type_dir:
                page_type = type_name
                break
        result_nodes.append({
            "id": nid,
            "label": n.get("label", nid),
            "page_type": page_type,
        })

    return {
        "nodes": result_nodes,
        "edges": display_edges,
        "stats": {
            "total_nodes": total_nodes,
            "displayed_nodes": len(result_nodes),
            "mode": display_mode,
        },
        "all_types": list(type_map.keys()),
    }
