"""Backward-compat shim: graph_export was moved to
``llmwikify.kernel.graph.export`` in Batch B3."""
from llmwikify.kernel.graph.export import *  # noqa: F401, F403
from llmwikify.kernel.graph.export import (  # noqa: F401
    _build_networkx,
    build_graph,
    compute_surprise_score,
    detect_communities,
    generate_report,
)
