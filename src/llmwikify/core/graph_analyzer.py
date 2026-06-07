"""Backward-compat shim: graph_analyzer was moved to
``llmwikify.kernel.graph.analyzer`` in Batch B3."""
from llmwikify.kernel.graph.analyzer import *  # noqa: F401, F403
from llmwikify.kernel.graph.analyzer import GraphAnalyzer  # noqa: F401
