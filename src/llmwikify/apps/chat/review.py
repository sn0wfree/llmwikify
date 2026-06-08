"""Backward-compat shim: ``llmwikify.apps.chat.review`` →
``llmwikify.apps.chat.harness.review`` (v0.32 Phase 7).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.harness.review import *  # noqa: F401, F403
