"""Backward-compat shim: ``core.lint.rules`` → ``kernel.wiki.lint.rules`` in Batch B3."""
from llmwikify.kernel.wiki.lint.rules import *  # noqa: F401, F403
from llmwikify.kernel.wiki.lint.rules import RULES  # noqa: F401
