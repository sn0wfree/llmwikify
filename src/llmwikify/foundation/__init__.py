"""L1 foundation layer — platform basics.

Per the 4-layer refactor (see
``docs/designs/refactor-4layer-architecture.md``), this package
contains the lowest-level building blocks that everything else
depends on. It MUST NOT import from ``llmwikify.kernel``,
``llmwikify.apps``, or ``llmwikify.interfaces``.

Subpackages:
    - llm: LLM client wrappers and token utilities
    - extractors: content extraction (PDF, web, YouTube, ...)
    - prompts: prompt template registry
    - templates: non-Python template assets (MCP configs, agent skills)
    - io: shared file/cache/serialization utilities

Top-level modules:
    - config: configuration loading and defaults
    - logging: unified ``setup_logging`` entry point + ``log_timing``
      decorator (single source for root logger configuration)
    - llm_client: the LLMClient base class (re-exported as
      ``llmwikify.foundation.llm.LLMClient``)
"""
