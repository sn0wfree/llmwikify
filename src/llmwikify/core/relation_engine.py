"""Backward-compat shim: relation_engine was moved to
``llmwikify.kernel.wiki.engines.relation`` in Batch B3."""
from llmwikify.kernel.wiki.engines.relation import *  # noqa: F401, F403
from llmwikify.kernel.wiki.engines.relation import RelationEngine  # noqa: F401
