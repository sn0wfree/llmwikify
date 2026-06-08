"""Backward-compat shim: ``llmwikify.apps.chat.quality_gate`` →
``llmwikify.apps.chat.harness.quality_gate`` (v0.32 Phase 7).

Phase 7 moved the 5 evaluation classes into the
``apps/chat/harness/`` subpackage. This shim preserves the
old import paths for callers that haven't migrated yet.

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.harness.quality_gate import *  # noqa: F401, F403
