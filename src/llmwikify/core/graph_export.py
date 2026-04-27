"""Graph export and community detection for knowledge visualization."""

import json
import logging
from pathlib import Path

from .index import WikiIndex

logger = logging.getLogger(__name__)


def build_graph(index: WikiIndex, include_wikilinks: bool = True, include_relations: bool = True) -> dict:
    """Build a combined graph from wikilinks and relations.

    Returns:
        Dict with 'nodes' and 'edges' lists suitable for NetworkX.
    """
    nodes = {}
    edges = []

    # Wikilinks
    if include_wikilinks:
        cursor = index.conn.execute(
            "SELECT source_page, target_page FROM page_links"
        )
        for row in cursor.fetchall():
            src, tgt = row["source_page"], row["target_page"]
            nodes[src] = {"id": src, "label": src, "source_type": "wiki_page"}
            nodes[tgt] = {"id": tgt, "label": tgt, "source_type": "wiki_page"}

            existing = next((e for e in edges if e["source"] == src and e["target"] == tgt and e["type"] == "wikilink"), None)
            if existing:
                existing["weight"] += 1
            else:
                edges.append({"source": src, "target": tgt, "type": "wikilink", "weight": 1})

    # Relations
    if include_relations:
        try:
            cursor = index.conn.execute(
                "SELECT source, target, relation, confidence FROM relations"
            )
            for row in cursor.fetchall():
                src, tgt = row["source"], row["target"]
                nodes[src] = {"id": src, "label": src, "source_type": "concept"}
                nodes[tgt] = {"id": tgt, "label": tgt, "source_type": "concept"}
                edges.append({
                    "source": src,
                    "target": tgt,
                    "type": row["relation"],
                    "confidence": row["confidence"],
                    "weight": {"EXTRACTED": 3, "INFERRED": 2, "AMBIGUOUS": 1}.get(row["confidence"], 1),
                })
        except Exception as e:
            logger.warning("Relations table query failed: %s", e)

    return {"nodes": list(nodes.values()), "edges": edges}


def export_html(graph: dict, communities: dict[int, list[str]] | None, output_path: Path, min_degree: int = 0) -> dict:
    """Export graph to interactive HTML using pyvis.

    Nodes with corresponding entity pages are clickable.
    """
    try:
        import networkx as nx
        from pyvis.network import Network
    except ImportError:
        raise ImportError("pyvis and networkx are required for HTML export. Install with: pip install pyvis networkx")

    G = _build_networkx(graph)

    # Filter by degree
    if min_degree > 0:
        degree = dict(G.degree())
        G = G.subgraph(n for n, d in degree.items() if d >= min_degree).copy()

    net = Network(height="750px", width="100%", bgcolor="#0f0f1a", font_color="#e0e0e0", directed=True)
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=250, spring_strength=0.001, damping=0.09)

    # Color nodes by community
    community_colors = [
        "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
        "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    ]
    node_community = {}
    if communities:
        for cid, node_list in communities.items():
            for n in node_list:
                node_community[n] = cid

    # Track which nodes have entity pages
    nodes_with_pages = set()

    for node, data in G.nodes(data=True):
        cid = node_community.get(node, -1)
        color = community_colors[cid % len(community_colors)] if cid >= 0 else "#888888"
        size = max(10, min(30, G.degree(node) * 3))
        source_type = data.get("source_type", "wiki_page")

        # Check if entity page exists
        href = None
        if source_type == "wiki_page":
            # Strip directory prefix before slugifying (e.g., "entities/Gold" → "Gold")
            base_name = node.rsplit('/', 1)[-1] if '/' in node else node
            entity_path = output_path.parent.parent / "wiki" / "entities" / f"{_slugify(base_name)}.md"
            if entity_path.exists():
                href = f"../wiki/entities/{_slugify(base_name)}.md"
                nodes_with_pages.add(node)
                color = "#59A14F"  # Green for entities with pages

        title_parts = [f"Degree: {G.degree(node)}", f"Type: {source_type}"]
        if href:
            title_parts.append(f"Click to open: {href}")

        title = "\n".join(title_parts)
        net.add_node(node, label=node, color=color, size=size, title=title)

    for u, v, data in G.edges(data=True):
        edge_type = data.get("type", "unknown")
        confidence = data.get("confidence", "")
        is_dashed = confidence == "AMBIGUOUS"
        net.add_edge(u, v, title=f"{edge_type} ({confidence})", dashes=is_dashed, width=data.get("weight", 1) * 0.5)

    net.show(str(output_path), notebook=False)

    # Post-process HTML to add click handlers for entity nodes
    if nodes_with_pages:
        _add_entity_click_handlers(output_path, nodes_with_pages)

    return {
        "status": "success",
        "output": str(output_path),
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "entity_pages_linked": len(nodes_with_pages),
    }


def _slugify(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    import re
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9\s-]', '', name)
    name = re.sub(r'[\s]+', '-', name)
    return name.strip('-')


def _add_entity_click_handlers(html_path: Path, entity_nodes: set) -> None:
    """Add JavaScript click handlers to make entity nodes clickable in the HTML graph."""
    if not html_path.exists():
        return

    html_content = html_path.read_text()

    # Build a map of node labels to their hrefs
    entity_map = {}
    for node in entity_nodes:
        base_name = node.rsplit('/', 1)[-1] if '/' in node else node
        slug = _slugify(base_name)
        entity_map[node] = f"../wiki/entities/{slug}.md"

    # Inject JavaScript before </body>
    js_code = """
<script>
(function() {
    const entityMap = __ENTITY_MAP__;
    const networkInstance = Object.values(window).find(v => v && typeof v.click === 'function' && v.body);

    if (networkInstance && networkInstance.on) {
        networkInstance.on('click', function(params) {
            if (params.nodes && params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                const label = this.body.nodes[nodeId]?.options.label || nodeId;
                if (entityMap[label]) {
                    window.open(entityMap[label], '_blank');
                }
            }
        });
    }

    // Fallback: style clickable nodes with a subtle ring
    document.querySelectorAll('div.vis-network svg g.vis-node').forEach(function(g) {
        const text = g.querySelector('text');
        if (text && entityMap[text.textContent]) {
            g.style.cursor = 'pointer';
        }
    });
})();
</script>
""".replace("__ENTITY_MAP__", json.dumps(entity_map))

    if "</body>" in html_content:
        html_content = html_content.replace("</body>", js_code + "\n</body>")
        html_path.write_text(html_content)


def export_graphml(graph: dict, output_path: Path) -> dict:
    """Export graph to GraphML format (compatible with Gephi, yEd)."""
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("networkx is required for GraphML export")

    G = _build_networkx(graph)

    # Convert to undirected for GraphML compatibility
    G_undirected = G.to_undirected()

    nx.write_graphml(G_undirected, str(output_path))

    return {
        "status": "success",
        "output": str(output_path),
        "nodes": G_undirected.number_of_nodes(),
        "edges": G_undirected.number_of_edges(),
    }


def export_svg(graph: dict, output_path: Path) -> dict:
    """Export graph to SVG using graphviz."""
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("networkx is required for SVG export")

    try:
        import subprocess

        from networkx.drawing.nx_agraph import write_dot
    except ImportError:
        raise ImportError("pygraphviz is required for SVG export. Install with: pip install pygraphviz")

    G = _build_networkx(graph)
    G_undirected = G.to_undirected()

    dot_path = str(output_path).replace(".svg", ".dot")
    write_dot(G_undirected, dot_path)

    # Convert DOT to SVG
    result = subprocess.run(
        ["dot", "-Tsvg", dot_path, "-o", str(output_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"graphviz dot failed: {result.stderr}")

    # Clean up DOT file
    Path(dot_path).unlink(missing_ok=True)

    return {
        "status": "success",
        "output": str(output_path),
        "nodes": G_undirected.number_of_nodes(),
        "edges": G_undirected.number_of_edges(),
    }


def detect_communities(index: WikiIndex, algorithm: str = "leiden", resolution: float = 1.0) -> dict:
    """Detect communities in the knowledge graph.

    Args:
        index: WikiIndex instance.
        algorithm: 'leiden' or 'louvain'.
        resolution: Resolution parameter (higher = more communities).

    Returns:
        Dict with community info.
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("networkx is required for community detection")

    graph = build_graph(index)
    G = _build_networkx(graph)

    if G.number_of_nodes() == 0:
        return {
            "communities": {},
            "num_communities": 0,
            "modularity": 0.0,
            "total_nodes": 0,
            "total_edges": 0,
            "warning": "Wiki has no pages or relations yet.",
        }

    if G.number_of_edges() == 0:
        communities_dict = {i: [n] for i, n in enumerate(G.nodes())}
        return {
            "communities": communities_dict,
            "num_communities": len(communities_dict),
            "modularity": 0.0,
            "total_nodes": G.number_of_nodes(),
            "total_edges": 0,
            "warning": "Pages have no links or relations. Each page is its own community.",
        }

    if algorithm == "louvain":
        try:
            import community as community_louvain
        except ImportError:
            raise ImportError("python-louvain is required for Louvain algorithm")

        partition = community_louvain.best_partition(G.to_undirected(), resolution=resolution, weight="weight")
        modularity = community_louvain.modularity(partition, G.to_undirected(), weight="weight")
    else:
        # Default: use a simple greedy modularity approach (no igraph dependency)
        try:
            import community as community_louvain
        except ImportError:
            # Fallback to networkx built-in greedy modularity
            partition = _greedy_modularity_communities(G)
            modularity = _compute_modularity(G, partition)
        else:
            partition = community_louvain.best_partition(G.to_undirected(), resolution=resolution, weight="weight")
            modularity = community_louvain.modularity(partition, G.to_undirected(), weight="weight")

    # Invert partition: community_id -> [nodes]
    communities = {}
    for node, cid in partition.items():
        if cid not in communities:
            communities[cid] = []
        communities[cid].append(node)

    return {
        "communities": communities,
        "num_communities": len(communities),
        "modularity": round(modularity, 4),
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
    }


def compute_surprise_score(
    G,
    source: str,
    target: str,
    edge_data: dict,
    communities: dict[int, list[str]],
) -> tuple:
    """Compute surprise score for an edge (borrowed from graphify, adapted for llmwikify).

    Dimensions:
    1. Confidence: AMBIGUOUS(3) > INFERRED(2) > EXTRACTED(1)
    2. Cross source type (+2)
    3. Cross knowledge domain (+2)
    4. Cross community (+1)
    5. Peripheral to hub (+1)
    """
    score = 0
    reasons = []

    # 1. Confidence weight
    conf = edge_data.get("confidence", "EXTRACTED")
    conf_bonus = {"AMBIGUOUS": 3, "INFERRED": 2, "EXTRACTED": 1}.get(conf, 1)
    score += conf_bonus
    if conf in ("AMBIGUOUS", "INFERRED"):
        reasons.append(f"{conf.lower()} relation - not explicitly stated")

    # 2. Cross source type
    src_type = edge_data.get("source_type_a")
    tgt_type = edge_data.get("source_type_b")
    if src_type and tgt_type and src_type != tgt_type:
        score += 2
        reasons.append(f"crosses source types ({src_type} ↔ {tgt_type})")

    # 3. Cross community
    node_community = {}
    for cid, nodes in communities.items():
        for n in nodes:
            node_community[n] = cid

    cid_a = node_community.get(source)
    cid_b = node_community.get(target)
    if cid_a is not None and cid_b is not None and cid_a != cid_b:
        score += 1
        reasons.append("bridges separate communities")

    # 4. Peripheral to hub
    if source not in G or target not in G:
        deg_a = 0
        deg_b = 0
    else:
        try:
            deg_a = G.degree(source)
        except Exception:
            deg_a = len(list(G.neighbors(source)))
        try:
            deg_b = G.degree(target)
        except Exception:
            deg_b = len(list(G.neighbors(target)))
    if min(deg_a, deg_b) <= 2 and max(deg_a, deg_b) >= 5:
        score += 1
        reasons.append("peripheral node reaches hub")

    return score, reasons


def generate_report(index: WikiIndex, communities: dict | None = None, top_n: int = 10) -> str:
    """Generate a surprising connections report."""
    try:
        import networkx as nx
    except ImportError:
        raise ImportError("networkx is required for report generation")

    graph = build_graph(index)
    G = _build_networkx(graph)

    if communities is None:
        comm_result = detect_communities(index)
        communities = comm_result.get("communities", {})

    # Score all edges
    scored_edges = []
    for u, v, data in G.edges(data=True):
        if data.get("type") == "wikilink":
            continue  # Skip plain wikilinks
        score, reasons = compute_surprise_score(G, u, v, data, communities)
        scored_edges.append({
            "source": u,
            "target": v,
            "relation": data.get("type", "unknown"),
            "confidence": data.get("confidence", ""),
            "score": score,
            "reasons": reasons,
        })

    # Sort by score descending
    scored_edges.sort(key=lambda x: -x["score"])

    # Build report
    lines = [
        "# Unexpected Connections Report",
        "",
        "## Overview",
        f"- Total nodes: {G.number_of_nodes()}",
        f"- Total edges: {G.number_of_edges()}",
        f"- Communities: {len(communities)}",
        "",
        f"## Top {top_n} Most Unexpected Connections",
        "",
    ]

    for i, edge in enumerate(scored_edges[:top_n], 1):
        lines.append(f"### {i}. Surprise Score: {edge['score']}")
        lines.append(f"**{edge['source']}** → **{edge['target']}**")
        lines.append(f"- Relation: {edge['relation']}")
        if edge['confidence']:
            lines.append(f"- Confidence: {edge['confidence']}")
        for reason in edge['reasons']:
            lines.append(f"- {reason}")
        lines.append("")

    if not scored_edges:
        lines.append("No unexpected connections found. The graph may be too small.")

    return "\n".join(lines)


def _build_networkx(graph: dict):
    """Build a NetworkX MultiDiGraph from graph dict."""
    import networkx as nx

    G = nx.MultiDiGraph()

    for node in graph.get("nodes", []):
        G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})

    for edge in graph.get("edges", []):
        G.add_edge(edge["source"], edge["target"], **edge)

    return G


def _greedy_modularity_communities(G):
    """Simple greedy modularity communities using networkx."""
    from networkx.algorithms.community import greedy_modularity_communities

    communities = greedy_modularity_communities(G.to_undirected(), weight="weight")
    return {node: cid for cid, comm in enumerate(communities) for node in comm}


def _compute_modularity(G, partition):
    """Compute modularity of a partition."""
    try:
        import community as community_louvain
        return community_louvain.modularity(partition, G.to_undirected(), weight="weight")
    except ImportError:
        # Fallback: return 0
        return 0.0
