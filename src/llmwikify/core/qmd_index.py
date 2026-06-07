"""Backward-compat shim: qmd_index was moved to
``llmwikify.kernel.search.qmd_index`` in Batch B3."""
from llmwikify.kernel.search.qmd_index import *  # noqa: F401, F403
from llmwikify.kernel.search.qmd_index import QmdIndex  # noqa: F401
