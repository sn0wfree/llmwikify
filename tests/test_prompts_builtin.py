"""Phase 9: prompts/builtin/ 核心测试.
"""
from __future__ import annotations


def test_hardcoded_system_prompt_code():
    from llmwikify.reproduction.codegen.llm_code import SYSTEM_PROMPT_CODE
    assert "compute_factor" in SYSTEM_PROMPT_CODE


def test_hardcoded_metadata_prompts():
    from llmwikify.reproduction.codegen.metadata import (
        SYSTEM_PROMPT_METADATA,
        SYSTEM_PROMPT_METADATA_V2,
    )
    assert SYSTEM_PROMPT_METADATA and SYSTEM_PROMPT_METADATA_V2


def test_hardcoded_react_feedback():
    from llmwikify.reproduction.codegen.feedback_templates import (
        OBSERVE_FEEDBACK_TEMPLATE,
    )
    assert "error" in OBSERVE_FEEDBACK_TEMPLATE
