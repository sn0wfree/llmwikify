"""kernel/quant/codegen/ — LLM-driven code generation primitives.

C1: extracted from `reproduction/codegen/llm_code.py` to break the
`reproduction/ ↔ apps/chat/agent/unified/` cycle. This module depends
only on `polars` + `QuantNodes` (third-party), and is the canonical
home for the following primitives:

  - code_extract.py:    extract_python / validate_syntax / validate_safety
                        / build_execute_namespace / execute_code
  - prompts.py:         SYSTEM_PROMPT_CODE (the codegen system prompt)
  - json_extract.py:    extract_json_from_response(text) → dict | None
  - feedback_templates.py: OBSERVE_FEEDBACK_TEMPLATE (used by ReAct self-repair)

The `reproduction/codegen/llm_code.py` module now re-exports these
for backward compatibility (and is marked deprecated).

Why split into 4 small files?
  - Each primitive is small and self-contained
  - Smaller files = more surgical imports = less chance of cycles
  - Easier to test in isolation

Why kernel/quant/ (not apps/quant/ or reproduction/codegen/)?
  - kernel/quant/ has no apps/ or reproduction/ dependency
  - apps/ and reproduction/ both depend on kernel/quant/
  - This is the correct layer in the dependency hierarchy

What about the higher-level `generate_factor_code` (ReAct loop)?
  - That's NOT here — it lives in apps/chat/agent/unified/pipelines/codegen.py
    (the implementation) and reproduction/codegen/llm_code.py
    (a thin re-export wrapper).
  - kernel/quant/codegen/ only holds the building blocks.
"""
from .code_extract import (
    build_execute_namespace,
    execute_code,
    extract_python,
    validate_safety,
    validate_syntax,
)
from .feedback_templates import OBSERVE_FEEDBACK_TEMPLATE
from .json_extract import extract_json_from_response
from .prompts import SYSTEM_PROMPT_CODE

__all__ = [
    # code_extract
    "extract_python",
    "validate_syntax",
    "validate_safety",
    "build_execute_namespace",
    "execute_code",
    # feedback_templates
    "OBSERVE_FEEDBACK_TEMPLATE",
    # json_extract
    "extract_json_from_response",
    # prompts
    "SYSTEM_PROMPT_CODE",
]
