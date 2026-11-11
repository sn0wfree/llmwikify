"""apps/chat/agent/unified — 通用框架 backward-compat + chat-specific agent.

架构说明:
- 通用框架 (UnifiedHook / UnifiedAgentLoop / StepHandler / Spec / Steps)
  已迁 kernel.agent。本包作为 backward-compat 层。
- chat-specific 部分 (events / hook_adapter / registry / handlers) 保留本包。

新代码应直接:
    from llmwikify.kernel.agent import UnifiedHook, UnifiedAgentLoop
    from llmwikify.apps.chat.agent.unified.handlers import ChatReasoner, ToolActor
    from llmwikify.apps.chat.agent.unified import registry, events, hook_adapter

状态标记 (2026-11-06):
- **生产零入口** — 导入图 BFS 只达测试; chat 主链路走 ChatRunnerV2。
- 处置方案: docs/designs/unified-loop-merge-plan.md。
- 因子编译路径 (CodegenReasoner / generate_factor_code / ExecuteCodeStep 等)
  已于 2026-11-10 删除；本项目不做因子编译。
"""

# 通用框架 re-export (from kernel.agent)
from llmwikify.foundation.utils import maybe_await as _maybe_await
from llmwikify.kernel.agent import (
    ActResult,
    BaseSpec,
    Pipeline,
    ReasonResponse,
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedAgentLoop,
    UnifiedContext,
    UnifiedHook,
    UnifiedResult,
)
from llmwikify.kernel.agent.steps import (
    CheckEmptyStep,
    CheckFieldStep,
    CheckSuccessStep,
    CheckToolCallsStep,
    ExtractCodeStep,
    ExtractJSONStep,
    LLMCallStep,
    MapStep,
    TruncateStep,
    ValidateSyntaxStep,
    WrapStep,
)

from .events import (  # noqa: F401
    ACTION_ERROR,
    COMMAND_DONE,
    COMPACTED,
    CONFIRMATION_REQUIRED,
    DONE,
    ERROR,
    MESSAGE_DELTA,
    OBSERVATION_ERROR,
    PHASE,
    REASONING,
    RESEARCH_RUN_STARTED,
    ROUND_COMPLETE,
    SAVE_WARNING,
    SESSION_CREATED,
    SESSION_INIT,
    THINKING,
    TIMEOUT,
    TOOL_CALL_END,
    TOOL_CALL_ERROR,
    TOOL_CALL_START,
    USER_MESSAGE,
)
from .handlers import ChatReasoner, ToolActor  # noqa: F401
from .hook_adapter import AgentHookAdapter  # noqa: F401
from .registry import (  # noqa: F401
    AgentModeConfig,
    create_agent_loop,
    get_mode_config,
    list_modes,
    register_mode,
)

# chat-specific
from .spec import ChatSpec

__all__ = [
    # Generic framework
    "StepHandler",
    "StreamingHandler",
    "StepResult",
    "Pipeline",
    "UnifiedHook",
    "UnifiedContext",
    "BaseSpec",
    "ChatSpec",
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
    "UnifiedAgentLoop",
    "_maybe_await",
    # Steps
    "CheckEmptyStep",
    "CheckFieldStep",
    "CheckSuccessStep",
    "CheckToolCallsStep",
    "ExtractCodeStep",
    "ExtractJSONStep",
    "LLMCallStep",
    "MapStep",
    "TruncateStep",
    "ValidateSyntaxStep",
    "WrapStep",
    # Chat-specific
    "ChatReasoner",
    "ToolActor",
    # Hook adapter
    "AgentHookAdapter",
    # Registry
    "AgentModeConfig",
    "register_mode",
    "get_mode_config",
    "list_modes",
    "create_agent_loop",
    # Events
    "SESSION_CREATED",
    "SESSION_INIT",
    "USER_MESSAGE",
    "MESSAGE_DELTA",
    "THINKING",
    "TOOL_CALL_START",
    "TOOL_CALL_END",
    "TOOL_CALL_ERROR",
    "CONFIRMATION_REQUIRED",
    "COMPACTED",
    "COMMAND_DONE",
    "RESEARCH_RUN_STARTED",
    "DONE",
    "ERROR",
    "SAVE_WARNING",
    "PHASE",
    "REASONING",
    "ACTION_ERROR",
    "OBSERVATION_ERROR",
    "ROUND_COMPLETE",
    "TIMEOUT",
]
