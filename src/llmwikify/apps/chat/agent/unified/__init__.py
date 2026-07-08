"""apps/chat/agent/unified — 通用框架 backward-compat + chat-specific agent.

架构说明:
- 通用框架 (UnifiedHook / UnifiedAgentLoop / StepHandler / Spec / Steps /
  generate_factor_code) 已迁 kernel.agent。本包作为 backward-compat 层。
- chat-specific 部分 (events / hook_adapter / registry / handlers) 保留本包。

新代码应直接:
    from llmwikify.kernel.agent import UnifiedHook, UnifiedAgentLoop
    from llmwikify.apps.chat.agent.unified.handlers import ChatReasoner, ToolActor
    from llmwikify.apps.chat.agent.unified import registry, events, hook_adapter

shim 设计:
- 顶层 __init__.py: 统一 re-export (统一从 kernel.agent)
- 子目录 pipelines/ 和 steps/: 保留 __init__.py shim (被广泛 import)
- 子目录 steps/{checks,code,feedback,llm,transforms}.py: 已删除 (内容在 kernel.agent.steps/)
- 子目录 pipelines/codegen.py: 已删除 (内容在 kernel.agent.codegen_pipeline.py)

历史: G+Y commit 2 (apps/unified/ 维度 A 拆解)。
"""
# 通用框架 re-export (from kernel.agent)
from llmwikify.kernel.agent import (
    ActResult,
    BaseSpec,
    CodeActor,
    CodegenReasoner,
    CodegenSpec,
    Pipeline,
    ReasonResponse,
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedAgentLoop,
    UnifiedContext,
    UnifiedHook,
    UnifiedResult,
    _maybe_await,
    generate_factor_code,
    generate_factor_code_sync,
)
from llmwikify.kernel.agent.steps import (
    BuildFeedbackStep,
    CheckEmptyStep,
    CheckFieldStep,
    CheckSuccessStep,
    CheckToolCallsStep,
    CodeExecResult,
    ExecuteCodeStep,
    ExtractCodeStep,
    ExtractJSONStep,
    LLMCallStep,
    MapStep,
    TruncateStep,
    ValidateAndExecuteStep,
    ValidateSafetyStep,
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
    "CodegenSpec",
    "ReasonResponse",
    "ActResult",
    "UnifiedResult",
    "UnifiedAgentLoop",
    "_maybe_await",
    # Codegen pipeline
    "CodegenReasoner",
    "CodeActor",
    "generate_factor_code",
    "generate_factor_code_sync",
    # Steps
    "BuildFeedbackStep",
    "CheckEmptyStep",
    "CheckFieldStep",
    "CheckSuccessStep",
    "CheckToolCallsStep",
    "CodeExecResult",
    "ExecuteCodeStep",
    "ExtractCodeStep",
    "ExtractJSONStep",
    "LLMCallStep",
    "MapStep",
    "TruncateStep",
    "ValidateAndExecuteStep",
    "ValidateSafetyStep",
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
    # Events (from .events import *)
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
