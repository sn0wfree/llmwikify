"""Backward-compat shim: ``llmwikify.apps.chat.structure_validator`` →
``llmwikify.apps.chat.harness.structure_validator`` (v0.32 Phase 7).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.harness.structure_validator import *  # noqa: F401, F403
