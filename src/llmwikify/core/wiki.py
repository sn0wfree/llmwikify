"""Backward-compat shim: wiki was moved to
``llmwikify.kernel.wiki.wiki`` in Batch B3."""
from llmwikify.kernel.wiki.wiki import *  # noqa: F401, F403
from llmwikify.kernel.wiki.wiki import VALID_AGENTS, Wiki  # noqa: F401
