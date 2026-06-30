"""kernel/codegen/ — LLM-driven code generation primitives.

历史: 从 kernel/quant/codegen/ 改名 (G+Y commit 5), 因为:
- 业务前缀 "quant" 误导 (这里的内容是 generic codegen 工具, 不是 quant-specific)
- 扁平化: code_extract.py → code_tools.py (语义更准)

依赖: polars + QuantNodes (third-party), 不依赖 apps/ 或 reproduction/。

包含 4 个 primitive:
  - code_tools.py: extract_python / validate_syntax / validate_safety
                    / build_execute_namespace / execute_code
  - prompts.py:    SYSTEM_PROMPT_CODE (codegen system prompt)
  - json_extract.py: extract_json_from_response(text) → dict | None
  - feedback_templates.py: OBSERVE_FEEDBACK_TEMPLATE (ReAct self-repair)

reproduction/codegen/llm_code.py 仍 re-export 这些 for backward compat。

generate_factor_code (ReAct loop) 不在这里 — 在 kernel/agent/codegen_pipeline.py。
"""
from .code_tools import (
    _PYTHON_FENCE_RE,
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
    # code_tools
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
