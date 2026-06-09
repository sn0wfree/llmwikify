"""Backward-compat shim: ``llmwikify.agent.backend.db`` →
``llmwikify.apps.chat.db`` + ``llmwikify.apps.db``
(Updated for v0.34.0: old apps.agent.core.db removed).

Update your imports. This shim will be removed in v0.35.0.
"""
from llmwikify.apps.db import AppDatabase  # noqa: F401
from llmwikify.apps.chat.db import ChatDatabase  # noqa: F401
from llmwikify.apps.research.db import ResearchDatabase  # noqa: F401
from llmwikify.apps.wiki.db import WikiDatabase  # noqa: F401
