"""Backward-compat shim: ``llmwikify.apps.chat.analyzer`` →
``llmwikify.apps.chat.harness.source_analyzer`` (v0.32 Phase 7).

The ``SourceAnalyzer`` class was renamed from ``analyzer.py``
to ``source_analyzer.py`` to make the 5 eval classes'
naming consistent (all named after their primary class).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.harness.source_analyzer import *  # noqa: F401, F403
