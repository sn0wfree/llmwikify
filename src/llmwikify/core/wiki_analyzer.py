"""Backward-compat shim: wiki_analyzer was moved to
``llmwikify.kernel.wiki.engines.analyzer`` in Batch B3."""
from llmwikify.kernel.wiki.engines.analyzer import *  # noqa: F401, F403
from llmwikify.kernel.wiki.engines.analyzer import WikiAnalyzer  # noqa: F401
