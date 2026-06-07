"""Backward-compat shim: wiki_registry was moved to
``llmwikify.kernel.multi_wiki.registry`` in Batch B3.

Per the 4-layer refactor design doc §1.4, this shim is
preserved until v0.33.0. Prefer the new path for new code.
"""
from llmwikify.kernel.multi_wiki.registry import *  # noqa: F401, F403
from llmwikify.kernel.multi_wiki.registry import WikiRegistry  # noqa: F401
