"""Research engine subpackage — thin wrapper (v0.40).

v0.40 collapsed the legacy split between ``apps.research`` and
``apps.chat.research_engine`` into a single canonical package at
``llmwikify.apps.research``. The actual implementations now live in:

  - ``llmwikify.apps.research.engine`` (ResearchEngine)
  - ``llmwikify.apps.research.gates`` (ResearchGates)
  - ``llmwikify.apps.research.llm_step`` (LLMCallMetrics, run_prompt)
  - ``llmwikify.apps.research.report`` (ReportGenerator)
  - ``llmwikify.apps.research.routes`` (FastAPI router)

Back-compat: callers using the legacy paths continue to work via
explicit submodule imports:

    from llmwikify.apps.chat.research_engine.engine import ResearchEngine
    from llmwikify.apps.chat.research_engine.gates import ResearchGates

The ``apps.chat.__init__`` re-exports the public API directly from the
canonical ``llmwikify.apps.research`` package.
"""

__all__: list[str] = []