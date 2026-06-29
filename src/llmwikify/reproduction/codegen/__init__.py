"""Codegen module — LLM code generation utilities.

Public API:
  - ReActProgressHook: UnifiedHook subclass for ReAct progress logging
  - llm_code_react: ReAct self-retry code generation (no RunConfig dep)

Internal helpers (existing):
  - llm_code.py, react_engine.py, repair.py, compiler.py (pre-existing)
"""
from __future__ import annotations

from .react_runner import ReActProgressHook, llm_code_react

__all__ = [
    "ReActProgressHook",
    "llm_code_react",
]
