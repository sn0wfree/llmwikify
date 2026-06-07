"""Backward-compat shim: graph_visualizer was moved to
``llmwikify.kernel.graph.visualizer`` in Batch B3."""
from llmwikify.kernel.graph.visualizer import *  # noqa: F401, F403
from llmwikify.kernel.graph.visualizer import build_visualization_data  # noqa: F401
