"""Knowledge graph analysis, export, and visualization.

The ``graph`` subpackage provides:

- ``analyzer``: community detection, centralities (PageRank,
  betweenness), knowledge-gap suggestions.
- ``export``: graph builders and community detection that
  consume a ``WikiIndex``.
- ``visualizer``: convert the graph to a JSON shape suitable
  for the WebUI graph explorer.
"""
from .analyzer import GraphAnalyzer
from .export import build_graph, detect_communities, generate_report
from .visualizer import build_visualization_data

__all__ = [
    "GraphAnalyzer",
    "build_graph",
    "detect_communities",
    "generate_report",
    "build_visualization_data",
]
