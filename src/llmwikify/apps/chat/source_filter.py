"""Backward-compat shim: ``llmwikify.apps.chat.source_filter`` →
``llmwikify.apps.chat.harness.source_filter`` (v0.32 Phase 7).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.harness.source_filter import *  # noqa: F401, F403
