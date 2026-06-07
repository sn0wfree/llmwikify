"""Backward-compat shim: protocols was moved to
``llmwikify.kernel.wiki.protocols`` in Batch B3."""
from llmwikify.kernel.wiki.protocols import *  # noqa: F401, F403
from llmwikify.kernel.wiki.protocols import WikiProtocol  # noqa: F401
