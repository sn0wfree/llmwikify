"""kernel/agent — 通用 agent 框架.

提供 Agent Loop 的核心抽象，与具体应用（chat / codegen / research）解耦：

- hook.UnifiedHook: 16 个 no-op hook 事件点
- context.UnifiedContext: Loop 内部状态
- execution_context.AgentExecutionContext: 共享 collaborators dataclass
- loop.UnifiedAgentLoop + core types (StepHandler / StepResult / StreamingHandler / Pipeline)
- spec.BaseSpec / CodegenSpec / ReasonResponse / ActResult / UnifiedResult
- codegen_pipeline: 高层 codegen pipeline (CodegenReasoner / CodeActor / generate_factor_code*)
- steps/: 15 个无状态 StepHandler (LLMCall / ExtractCode / ValidateAndExecute / CheckSuccess / ...)

历史: 从 apps/chat/agent/unified/ 搬迁 (维度 A 拆解).
apps/chat/agent/unified/ 保留为 backward-compat shim.
"""
from ._core_types import (
    Pipeline,
    StepHandler,
    StepResult,
    StreamingHandler,
    _maybe_await,
)
from .codegen_pipeline import (
    CodeActor,
    CodegenReasoner,
    generate_factor_code,
    generate_factor_code_sync,
)
from .context import UnifiedContext
from .execution_context import AgentExecutionContext
from .hook import UnifiedHook
from .loop import UnifiedAgentLoop
from .spec import (
    ActResult,
    BaseSpec,
    CodegenSpec,
    ReasonResponse,
    UnifiedResult,
)

__all__ = [
    # Hook
    "UnifiedHook",
    # Context
    "UnifiedContext",
    # Execution context
    "AgentExecutionContext",
    # Loop
    "UnifiedAgentLoop",
    # Spec / Result
    "BaseSpec",
    "CodegenSpec",
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
    # Codegen pipeline
    "CodegenReasoner",
    "CodeActor",
    "generate_factor_code",
    "generate_factor_code_sync",
    # Core types
    "StepHandler",
    "StepResult",
    "StreamingHandler",
    "Pipeline",
    "_maybe_await",
]
