"""Backward-compat shim: synthesis_engine was moved to
``llmwikify.kernel.wiki.engines.synthesis`` in Batch B3."""
from llmwikify.kernel.wiki.engines.synthesis import *  # noqa: F401, F403
from llmwikify.kernel.wiki.engines.synthesis import SynthesisEngine  # noqa: F401
