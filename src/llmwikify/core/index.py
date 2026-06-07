"""Backward-compat shim: index was moved to
``llmwikify.kernel.storage.index`` in Batch B3."""
from llmwikify.kernel.storage.index import *  # noqa: F401, F403
from llmwikify.kernel.storage.index import WikiIndex  # noqa: F401
