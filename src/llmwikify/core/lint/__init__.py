"""Backward-compat shim: ``core.lint`` → ``kernel.wiki.lint`` in Batch B3."""
from llmwikify.kernel.wiki.lint import *  # noqa: F401, F403
from llmwikify.kernel.wiki.lint import (  # noqa: F401
    LintEngine,
    Rule,
)
