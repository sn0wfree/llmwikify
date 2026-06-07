"""Backward-compat shim: prompt_registry was moved to
``llmwikify.kernel.wiki.prompt_registry`` in Batch B3."""
from llmwikify.kernel.wiki.prompt_registry import *  # noqa: F401, F403
from llmwikify.kernel.wiki.prompt_registry import PromptRegistry  # noqa: F401
