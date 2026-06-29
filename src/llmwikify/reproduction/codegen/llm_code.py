"""Shared codegen utilities for factor code generation pipeline.

⚠️ C1 (PR-C1) refactor: this module is now a **thin re-export wrapper** for
backward compatibility. The actual implementations live in
`llmwikify.kernel.quant.codegen` (which both apps/ and reproduction/ can
import without creating a layer cycle).

New code should import from `llmwikify.kernel.quant.codegen` directly.
This wrapper exists for backward compat with pre-C1 callers.

Functions kept here (reproduction-specific):
  - build_llm_client: thin wrapper over reproduction.common.llm_factory.
    Will be replaced by provider registry in C2.
  - generate_factor_code: high-level ReAct entry point. The actual
    implementation lives in apps/chat/agent/unified/pipelines/codegen.py
    (cross-layer dependency, kept here for backward compat).

Re-exports from kernel/quant/codegen/:
  - SYSTEM_PROMPT_CODE
  - extract_python
  - validate_syntax
  - validate_safety
  - build_execute_namespace
  - execute_code
  - extract_json_from_response
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import polars as pl

# C1: re-export from kernel/quant/codegen/
from llmwikify.kernel.quant.codegen import (  # noqa: F401
    _PYTHON_FENCE_RE,
    OBSERVE_FEEDBACK_TEMPLATE,
    SYSTEM_PROMPT_CODE,
    build_execute_namespace,
    execute_code,
    extract_json_from_response,
    extract_python,
    validate_safety,
    validate_syntax,
)

logger = logging.getLogger(__name__)


# ─── LLM client (reproduction-specific, C2 will fix) ─────────────

def build_llm_client(model: str | None = None) -> Any:
    """Build StreamableLLMClient from ~/.llmwikify/llmwikify.json.

    Thin wrapper around llm_extraction.llm_factory.build_default_client().
    Centralizes client creation so callers don't parse config manually.

    ⚠️ TODO(C2): this function hardcodes `minimax` / `bearer` via
    `reproduction.common.llm_factory.build_default_client`. Will be replaced
    by a provider-registry-based factory in C2.

    Args:
        model: Override model name (default: config's model field).

    Returns:
        Configured StreamableLLMClient instance.

    Raises:
        RuntimeError: If config missing, disabled, or required fields absent.
    """
    from ..common.llm_factory import build_default_client
    return build_default_client(model=model)


# ─── High-level convenience (reproduction-specific) ──────────────

def generate_factor_code(
    factor_name: str,
    formula_brief: str,
    df: pl.DataFrame,
    *,
    llm: Any | None = None,
    system_prompt: str | None = None,
    max_repair_rounds: int = 3,
    temperature: float = 0.3,
    model: str | None = None,
    progress_callback: Any | None = None,
    prompts: Any | None = None,
) -> tuple[str | None, pl.Series | None, str | None, dict]:
    """High-level convenience: build client (if needed) + run unified codegen loop.

    Returns (code, factor_series, error, result_dict).

    Args:
        factor_name: Display name (e.g. "alpha-001").
        formula_brief: Natural-language formula description.
        df: Polars DataFrame in long format.
        llm: Pre-built LLM client (if None, calls build_llm_client(model)).
        system_prompt: System prompt (if None, uses SYSTEM_PROMPT_CODE or prompts).
        max_repair_rounds: Max self-repair iterations (default 3).
        temperature: LLM temperature (default 0.3).
        model: Override model name (only used if llm is None).
        progress_callback: Unused (kept for backward compat).
        prompts: Optional PromptRegistry. When provided and system_prompt is None,
                 looks up "code_gen" prompt from registry.

    Returns:
        (code, factor_series, error_message, result_dict)
        where code/series are None on failure, error is None on success.
    """
    warnings.warn(
        "reproduction.codegen.llm_code.generate_factor_code is deprecated; "
        "use llmwikify.apps.chat.agent.unified.pipelines.codegen.generate_factor_code_sync "
        "directly. This wrapper will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import (
        generate_factor_code_sync,
    )

    if llm is None:
        llm = build_llm_client(model=model)
    if system_prompt is None:
        if prompts is not None:
            try:
                group = prompts.get("code_gen", version="latest")
                system_prompt = group.system
            except (KeyError, AttributeError):
                system_prompt = SYSTEM_PROMPT_CODE
        else:
            system_prompt = SYSTEM_PROMPT_CODE

    result = generate_factor_code_sync(
        factor_name=factor_name,
        formula_brief=formula_brief,
        df=df,
        llm_client=llm,
        system_prompt=system_prompt,
        max_repair_rounds=max_repair_rounds,
        temperature=temperature,
    )

    if result.error:
        return None, None, result.error, result.to_dict()

    return result.code, result.factor_series, None, result.to_dict()


__all__ = [
    "SYSTEM_PROMPT_CODE",
    "OBSERVE_FEEDBACK_TEMPLATE",
    "build_llm_client",
    "extract_python",
    "validate_syntax",
    "validate_safety",
    "build_execute_namespace",
    "execute_code",
    "extract_json_from_response",
    "generate_factor_code",
]
