"""Prompt templates for LLM interactions."""

# Per the 4-layer refactor (Batch B1), ``prompts/`` moved to
# ``foundation/``. The ``core`` import is absolute (not relative)
# so the link survives the B3 move of ``core/`` → ``kernel/``.
from llmwikify.core.prompt_registry import PromptRegistry

__all__ = ["PromptRegistry"]
