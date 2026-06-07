"""Backward-compat shim: qmd_client was moved to
``llmwikify.kernel.search.qmd_client`` in Batch B3."""
from llmwikify.kernel.search.qmd_client import *  # noqa: F401, F403
from llmwikify.kernel.search.qmd_client import QmdClient  # noqa: F401
