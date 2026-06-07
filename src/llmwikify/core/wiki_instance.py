"""Backward-compat shim: wiki_instance was moved to
``llmwikify.kernel.multi_wiki.instance`` in Batch B3."""
from llmwikify.kernel.multi_wiki.instance import *  # noqa: F401, F403
from llmwikify.kernel.multi_wiki.instance import (  # noqa: F401
    WikiInstance,
    WikiStatus,
    WikiType,
)
