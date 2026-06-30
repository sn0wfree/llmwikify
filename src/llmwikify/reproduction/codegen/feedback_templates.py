"""Shared feedback templates for codegen self-repair loops.

⚠️ C1 (PR-C1) refactor: this module is now a **thin re-export wrapper**
for backward compatibility. The actual template lives in
`llmwikify.kernel.codegen.feedback_templates`.

New code should import from `llmwikify.kernel.codegen` directly.
"""
from __future__ import annotations

from llmwikify.kernel.codegen.feedback_templates import (  # noqa: F401
    OBSERVE_FEEDBACK_TEMPLATE,
)

__all__ = ["OBSERVE_FEEDBACK_TEMPLATE"]
