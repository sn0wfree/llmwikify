"""Backward-compat shim: codegen.py 已迁 kernel.agent.codegen_pipeline.

历史: generate_factor_code + _sync + CodegenReasoner + CodeActor 已从
apps/chat/agent/unified/pipelines/codegen.py 搬到
kernel/agent/codegen_pipeline.py (commit 1 of G+Y)。

本 codegen.py 保留为 backward-compat re-export, 让旧 import path 仍工作:
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import (
        CodeActor, CodegenReasoner, generate_factor_code,
    )

新代码应直接:
    from llmwikify.kernel.agent import (
        CodeActor, CodegenReasoner,
        generate_factor_code, generate_factor_code_sync,
    )
"""
from llmwikify.kernel.agent.codegen_pipeline import (
    CodeActor,
    CodegenReasoner,
    generate_factor_code,
    generate_factor_code_sync,
)

__all__ = [
    "CodeActor",
    "CodegenReasoner",
    "generate_factor_code",
    "generate_factor_code_sync",
]
