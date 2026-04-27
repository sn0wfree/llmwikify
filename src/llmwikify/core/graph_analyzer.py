"""Knowledge graph analysis tools — PageRank, community labeling, page suggestions.

Design principle: "LLM does grunt work, human makes decisions"
- All analysis is read-only — never auto-creates pages
- Returns suggestions for human review
- Respects "stay involved" principle from LLM Wiki Principles
"""

import logging

from .graph_export import build_graph, detect_communities

logger = logging.getLogger(__name__)


class GraphAnalyzer:
    """Analyze knowledge graph structure and generate suggestions.

    Usage:
        analyzer = GraphAnalyzer(wiki)
        analysis = analyzer.analyze()
        # Returns: centrality, communities, suggestions, stats
    """

    def __init__(self, wiki):
        self.wiki = wiki

    def analyze(self) -> dict:
        """Run full graph analysis.

        Returns:
            Dict with:
            - centrality: PageRank scores and hub identification
            - communities: Community detection with labels
            - suggestions: Suggested pages to create
            - stats: Graph statistics
        """
        graph_data = self._get_graph_data()
        G = self._build_graph(graph_data)

        if G is None or G.number_of_nodes() == 0:
            return {
                "status": "empty",
                "message": "Wiki has no pages or relations yet. Add sources and create pages first.",
                "centrality": {},
                "communities": {},
                "suggestions": [],
                "stats": {"nodes": 0, "edges": 0},
            }

        return {
            "status": "success",
            "centrality": self._compute_centrality(G),
            "communities": self._analyze_communities(G),
            "suggestions": self._generate_suggestions(G, graph_data),
            "stats": self._compute_stats(G),
        }

    def _get_graph_data(self) -> dict:
        """Build graph data from wiki index."""
        try:
            return build_graph(
                self.wiki.index,
                include_wikilinks=True,
                include_relations=True,
            )
        except Exception as e:
            logger.warning("Graph build failed: %s", e)
            return {"nodes": [], "edges": []}

    def _build_graph(self, graph_data: dict):
        """Build NetworkX graph from graph data."""
        try:
            import networkx as nx
        except ImportError:
            return None

        G = nx.MultiDiGraph()

        for node in graph_data.get("nodes", []):
            G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})

        for edge in graph_data.get("edges", []):
            G.add_edge(edge["source"], edge["target"], **edge)

        return G

    def _compute_centrality(self, G) -> dict:
        """Compute PageRank and identify hub/authority nodes.

        Returns:
            Dict with:
            - pagerank: Top nodes by PageRank score
            - hubs: Nodes with high out-degree (connect to many)
            - authorities: Nodes with high in-degree (connected by many)
        """
        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx is required for centrality analysis"}

        # PageRank
        try:
            pagerank = nx.pagerank(G.to_undirected(), weight="weight")
        except Exception as e:
            logger.warning("PageRank computation failed: %s", e)
            pagerank = {}

        # Degree centrality
        try:
            in_degree = dict(G.in_degree())
            out_degree = dict(G.out_degree())
        except Exception as e:
            logger.warning("Degree computation failed: %s", e)
            in_degree = {}
            out_degree = {}

        # Sort by score
        top_pagerank = sorted(pagerank.items(), key=lambda x: -x[1])[:10]
        top_hubs = sorted(out_degree.items(), key=lambda x: -x[1])[:10]
        top_authorities = sorted(in_degree.items(), key=lambda x: -x[1])[:10]

        return {
            "pagerank": [
                {"node": node, "score": round(score, 4)}
                for node, score in top_pagerank
            ],
            "hubs": [
                {"node": node, "out_degree": degree}
                for node, degree in top_hubs
            ],
            "authorities": [
                {"node": node, "in_degree": degree}
                for node, degree in top_authorities
            ],
        }

    def _analyze_communities(self, G) -> dict:
        """Run community detection and label communities.

        Returns:
            Dict with community analysis:
            - communities: List of communities with members
            - labels: Suggested labels for each community
            - bridges: Nodes that connect multiple communities
        """
        try:
            comm_result = detect_communities(self.wiki.index, algorithm="leiden")
        except Exception as e:
            logger.warning("Community detection failed: %s", e)
            return {"error": "Community detection failed"}

        communities = comm_result.get("communities", {})
        num_communities = comm_result.get("num_communities", 0)

        # Label communities based on member node names
        labeled_communities = {}
        for cid, members in communities.items():
            label = self._label_community(members)
            labeled_communities[str(cid)] = {
                "label": label,
                "size": len(members),
                "members": sorted(members)[:20],  # Limit display
                "total_members": len(members),
            }

        # Find bridge nodes (connect multiple communities)
        bridges = self._find_bridge_nodes(G, communities)

        return {
            "num_communities": num_communities,
            "modularity": comm_result.get("modularity", 0),
            "communities": labeled_communities,
            "bridges": bridges[:10],  # Top 10 bridges
        }

    def _label_community(self, members: list[str]) -> str:
        """Generate a label for a community based on member names.

        Strategy:
        1. Find most common directory prefix
        2. Use most common keyword
        3. Fallback to generic label
        """
        if not members:
            return "Unknown"

        # Count directory prefixes
        prefix_counts = {}
        for member in members:
            prefix = member.split('/')[0] if '/' in member else 'root'
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

        if prefix_counts:
            dominant_prefix = max(prefix_counts, key=prefix_counts.get)
            if prefix_counts[dominant_prefix] >= len(members) * 0.5:
                return f"{dominant_prefix.title()} Community"

        # Use first few members as label
        short_names = [m.split('/')[-1] for m in members[:3]]
        if len(members) > 3:
            return f"{short_names[0]} + {len(members)-1} more"
        return ", ".join(short_names)

    def _find_bridge_nodes(self, G, communities: dict) -> list[dict]:
        """Find nodes that connect multiple communities.

        Returns:
            List of bridge nodes with their community connections.
        """
        try:
            import networkx as nx
        except ImportError:
            return []

        # Build node -> community mapping
        node_community = {}
        for cid, members in communities.items():
            for member in members:
                node_community[member] = cid

        bridges = []
        for node in G.nodes():
            if node not in node_community:
                continue

            # Count unique communities of neighbors
            neighbor_communities = set()
            try:
                for neighbor in G.neighbors(node):
                    if neighbor in node_community:
                        neighbor_communities.add(node_community[neighbor])
            except Exception as e:
                logger.warning("Neighbor iteration failed for node %s: %s", node, e)

            if len(neighbor_communities) > 1:
                bridges.append({
                    "node": node,
                    "communities_connected": len(neighbor_communities),
                    "observation": f"Connects {len(neighbor_communities)} communities",
                })

        # Sort by number of communities connected
        bridges.sort(key=lambda x: -x["communities_connected"])
        return bridges

    def _generate_suggestions(self, G, graph_data: dict) -> list[dict]:
        """Generate suggestions for improving the knowledge graph.

        Types of suggestions:
        1. Missing pages for high-degree concepts
        2. Orphan concepts in relations without wiki pages
        3. Under-connected pages that need more wikilinks
        4. Potential page merges (similar nodes)
        """
        suggestions = []

        # 1. High-degree concepts without wiki pages
        suggestions.extend(self._suggest_pages_for_concepts(G))

        # 2. Orphan concepts from relation engine
        suggestions.extend(self._suggest_orphan_pages())

        # 3. Under-connected pages
        suggestions.extend(self._suggest_link_improvements(G))

        return suggestions

    def _suggest_pages_for_concepts(self, G) -> list[dict]:
        """Suggest creating pages for high-degree concepts that lack wiki pages."""
        suggestions = []

        try:
            import networkx as nx
        except ImportError:
            return suggestions

        for node, degree in G.degree():
            if degree < 2:
                continue

            # Check if wiki page exists
            node_type = G.nodes[node].get("source_type", "unknown")
            if node_type == "concept" and not self._page_exists(node):
                suggestions.append({
                    "type": "create_page",
                    "node": node,
                    "degree": degree,
                    "priority": "high" if degree >= 3 else "medium",
                    "observation": f"'{node}' has {degree} connections but no wiki page",
                    "suggestion": f"Create a page for '{node}' to document this concept",
                })

        # Sort by degree descending
        suggestions.sort(key=lambda x: -x["degree"])
        return suggestions[:10]

    def _suggest_orphan_pages(self) -> list[dict]:
        """Suggest creating pages for orphan concepts in the relation engine."""
        suggestions = []

        try:
            engine = self.wiki.get_relation_engine()
            orphans = engine.find_orphan_concepts()
            for concept in orphans[:5]:
                suggestions.append({
                    "type": "create_orphan_page",
                    "concept": concept,
                    "priority": "medium",
                    "observation": f"'{concept}' is in the knowledge graph but has no wiki page",
                    "suggestion": f"Consider creating entities/{concept}.md or concepts/{concept}.md",
                })
        except Exception as e:
            logger.warning("Orphan concept lookup failed: %s", e)

        return suggestions

    def _suggest_link_improvements(self, G) -> list[dict]:
        """Suggest improving wikilinks for under-connected pages."""
        suggestions = []

        # Find pages with low degree that should have more connections
        for node, degree in G.degree():
            if degree == 0:
                node_type = G.nodes[node].get("source_type", "unknown")
                if node_type == "wiki_page":
                    suggestions.append({
                        "type": "add_wikilinks",
                        "node": node,
                        "priority": "low",
                        "observation": f"'{node}' has no links to other pages",
                        "suggestion": "Add wikilinks to connect this page to related concepts",
                    })

        return suggestions[:5]

    def _page_exists(self, node: str) -> bool:
        """Check if a wiki page exists for the given node name."""
        # Check if page exists in any subdirectory
        if not self.wiki.wiki_dir.exists():
            return False

        for md_file in self.wiki.wiki_dir.rglob("*.md"):
            page_name = str(md_file.relative_to(self.wiki.wiki_dir))[:-3]
            if page_name == node:
                return True
        return False

    def _compute_stats(self, G) -> dict:
        """Compute graph statistics."""
        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx required"}

        return {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "density": round(nx.density(G), 4) if G.number_of_nodes() > 0 else 0,
            "avg_degree": round(sum(dict(G.degree()).values()) / max(G.number_of_nodes(), 1), 2),
            "is_connected": nx.is_weakly_connected(G) if G.number_of_nodes() > 0 else False,
        }

    def get_suggested_pages_report(self) -> str:
        """Generate a human-readable report of suggested pages."""
        analysis = self.analyze()

        if analysis["status"] == "empty":
            return analysis["message"]

        lines = [
            "# Knowledge Graph Analysis Report",
            "",
            "## Overview",
            f"- Nodes: {analysis['stats']['nodes']}",
            f"- Edges: {analysis['stats']['edges']}",
            f"- Density: {analysis['stats']['density']}",
            f"- Connected: {'Yes' if analysis['stats']['is_connected'] else 'No'}",
            "",
            "## Core Concepts (by PageRank)",
            "",
        ]

        for item in analysis["centrality"].get("pagerank", [])[:5]:
            lines.append(f"- **{item['node']}** (score: {item['score']})")

        lines.extend([
            "",
            "## Communities",
            "",
        ])

        for _cid, comm in analysis["communities"].get("communities", {}).items():
            lines.append(f"- **{comm['label']}**: {comm['size']} nodes")

        lines.extend([
            "",
            "## Bridge Nodes",
            "",
        ])

        for bridge in analysis["communities"].get("bridges", [])[:5]:
            lines.append(f"- **{bridge['node']}**: {bridge['observation']}")

        lines.extend([
            "",
            "## Suggested Pages",
            "",
        ])

        for sugg in analysis["suggestions"]:
            lines.append(f"- [{sugg['priority'].upper()}] {sugg['observation']}")
            lines.append(f"  → {sugg['suggestion']}")

        if not analysis["suggestions"]:
            lines.append("No suggestions at this time.")

        return "\n".join(lines)
