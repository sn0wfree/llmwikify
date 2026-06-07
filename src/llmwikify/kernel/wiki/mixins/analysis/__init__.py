"""Lint delegation, LLM calls, query, relations, synthesis, status mixins.

These six mixins are the higher-level operations the Wiki
class performs: lint rule delegation, LLM-backed analysis,
querying, relation handling, synthesis generation, and
status reports.
"""
from .lint import WikiLintMixin
from .llm import WikiLLMMixin
from .query import WikiQueryMixin
from .relation import WikiRelationMixin
from .status import WikiStatusMixin
from .synthesis import WikiSynthesisMixin

__all__ = [
    "WikiLintMixin",
    "WikiLLMMixin",
    "WikiQueryMixin",
    "WikiRelationMixin",
    "WikiStatusMixin",
    "WikiSynthesisMixin",
]
