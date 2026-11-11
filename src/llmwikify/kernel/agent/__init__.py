"""kernel/agent — 通用 agent 框架.

提供 Agent Loop 的核心抽象，与具体应用（chat / research）解耦：

- hook.UnifiedHook: 16 个 no-op hook 事件点
- context.UnifiedContext: Loop 内部状态
- execution_context.AgentExecutionContext: 共享 collaborators dataclass
- loop.UnifiedAgentLoop + core types (StepHandler / StepResult / StreamingHandler / Pipeline)
- spec.BaseSpec / ReasonResponse / ActResult / UnifiedResult
- steps/: 无状态 StepHandler（LLMCall / ExtractCode / Check* / ...）

历史: 从 apps/chat/agent/unified/ 搬迁 (维度 A 拆解).
apps/chat/agent/unified/ 保留为 backward-compat shim.
因子编译 pipeline（CodegenReasoner / generate_factor_code）已删除。
"""

from ._core_types import (
    Pipeline,
    StepHandler,
    StepResult,
    StreamingHandler,
)
from .context import UnifiedContext
from .execution_context import AgentExecutionContext
from .hook import UnifiedHook
from .loop import UnifiedAgentLoop
from .spec import (
    ActResult,
    BaseSpec,
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
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
    # Core types
    "StepHandler",
    "StepResult",
    "StreamingHandler",
    "Pipeline",
]
