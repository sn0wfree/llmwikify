"""Backward-compat shim: wiki_discovery was moved to
``llmwikify.kernel.multi_wiki.discovery`` in Batch B3."""
from llmwikify.kernel.multi_wiki.discovery import *  # noqa: F401, F403
from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery  # noqa: F401
