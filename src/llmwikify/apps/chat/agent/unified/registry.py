"""注册表 — AgentModeConfig + register_mode + create_agent_loop。

声明式定义 agent 模式，工厂函数保证策略组合合法。

用法::

    from llmwikify.apps.chat.agent.unified.registry import (
        register_mode, create_agent_loop, AgentModeConfig,
    )

    register_mode(AgentModeConfig(
        name="validator",
        reasoner=Pipeline(ReadCodeStep(), ExtractCodeStep()),
        actor=ValidateAndExecuteStep(),
        deciders={"after_act": CheckFieldStep("success")},
    ))

    loop = create_agent_loop("validator")
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llmwikify.apps.chat.agent.unified.core import StepHandler, StreamingHandler, UnifiedHook
from llmwikify.apps.chat.agent.unified.spec import BaseSpec, ChatSpec


@dataclass
class AgentModeConfig:
    """一个 mode 的完整配置。

    reasoner/actor 可以是：
    - StepHandler 实例（无状态）
    - StreamingHandler 实例（有状态）
    - 工厂函数（callable，接收 **kwargs 返回 handler 实例）
    """

    name: str
    reasoner: StepHandler | StreamingHandler | Callable[..., Any]
    actor: StepHandler | StreamingHandler | Callable[..., Any]
    deciders: dict[str, StepHandler] = field(default_factory=dict)
    spec_cls: type = BaseSpec
    precheck: Callable[[Any], bool] | None = None
    finalize: Callable[[Any], str | None] | None = None
    hook_factory: Callable[..., UnifiedHook] | None = None


_MODE_REGISTRY: dict[str, AgentModeConfig] = {}


def register_mode(config: AgentModeConfig) -> None:
    """注册一个 mode。"""
    _MODE_REGISTRY[config.name] = config


def get_mode_config(name: str) -> AgentModeConfig | None:
    """获取已注册的 mode 配置。"""
    return _MODE_REGISTRY.get(name)


def list_modes() -> list[str]:
    """列出所有已注册的 mode 名称。"""
    return list(_MODE_REGISTRY.keys())


def create_agent_loop(name: str, **kwargs: Any) -> Any:
    """工厂 — 根据注册的 mode 名称创建 UnifiedAgentLoop。

    保证策略组合合法。如果 reasoner/actor 是工厂函数，用 kwargs 调用。

    Args:
        name: mode 名称（如 "chat", "codegen"）
        **kwargs: 传递给工厂函数的参数（如 chat_service, tool_executor, llm_client）

    Returns:
        UnifiedAgentLoop 实例

    Raises:
        ValueError: 未知的 mode 名称
    """
    from llmwikify.apps.chat.agent.unified.loop import UnifiedAgentLoop

    config = _MODE_REGISTRY.get(name)
    if config is None:
        available = list(_MODE_REGISTRY.keys())
        raise ValueError(f"Unknown mode: {name!r}. Available: {available}")

    reasoner = _resolve_handler(config.reasoner, kwargs)
    actor = _resolve_handler(config.actor, kwargs)
    hook = config.hook_factory(**kwargs) if config.hook_factory else None

    return UnifiedAgentLoop(
        reasoner=reasoner,
        actor=actor,
        deciders=config.deciders,
        hook=hook,
        precheck=config.precheck,
        finalize=config.finalize,
    )


def _resolve_handler(
    handler: StepHandler | StreamingHandler | Callable[..., Any],
    kwargs: dict[str, Any],
) -> StepHandler | StreamingHandler:
    """解析 handler：如果是工厂函数则调用，否则直接返回。"""
    if callable(handler) and not isinstance(handler, (StepHandler, StreamingHandler)):
        return handler(**kwargs)
    return handler


# ─── 预注册内置模式 ─────────────────────────────────────


def _chat_precheck(ctx: Any) -> bool:
    """Chat mode precheck：timeout / goal_abandoned / cancelled / paused。"""
    timeout = getattr(ctx.spec, "timeout_seconds", 0)
    if timeout and ctx.elapsed_sec > timeout:
        ctx.stop_reason = "timeout"
        return True
    pred = getattr(ctx.spec, "goal_active_predicate", None)
    if pred is not None:
        try:
            if not pred():
                ctx.stop_reason = "goal_abandoned"
                return True
        except Exception:
            pass
    return False


def _chat_finalize(ctx: Any) -> str | None:
    """Chat mode finalize：返回 final_content。"""
    return ctx.final_content


def _register_chat_mode() -> None:
    """注册 chat mode（延迟导入，Phase 6 实现后可用）。"""
    try:
        from llmwikify.apps.chat.agent.unified.steps import CheckEmptyStep

        register_mode(AgentModeConfig(
            name="chat",
            spec_cls=ChatSpec,
            reasoner=_make_chat_reasoner,
            actor=_make_tool_actor,
            deciders={"after_reason": CheckEmptyStep("tool_calls", "no_tool_calls")},
            hook_factory=_make_chat_hook,
            precheck=_chat_precheck,
            finalize=_chat_finalize,
        ))
    except ImportError:
        pass  # Phase 6 未实现时跳过


def _make_chat_reasoner(**kwargs: Any) -> Any:
    from llmwikify.apps.chat.agent.unified.handlers.chat_reasoner import ChatReasoner
    return ChatReasoner(kwargs["chat_service"], kwargs.get("prompt_builder"))


def _make_tool_actor(**kwargs: Any) -> Any:
    from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor
    return ToolActor(kwargs["tool_executor"])


def _make_chat_hook(**kwargs: Any) -> UnifiedHook:
    from llmwikify.apps.chat.agent.unified.hook_adapter import AgentHookAdapter
    return AgentHookAdapter(kwargs.get("hook"))


def _register_codegen_mode() -> None:
    """注册 codegen mode（延迟导入，Phase 4 实现后可用）。"""
    try:
        from llmwikify.apps.chat.agent.unified.pipelines.codegen import CodeActor, CodegenReasoner
        from llmwikify.apps.chat.agent.unified.steps import CheckSuccessStep

        register_mode(AgentModeConfig(
            name="codegen",
            reasoner=_make_codegen_reasoner,
            actor=CodeActor(),
            deciders={"after_act": CheckSuccessStep()},
        ))
    except ImportError:
        pass  # Phase 4 未实现时跳过


def _make_codegen_reasoner(**kwargs: Any) -> Any:
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import CodegenReasoner
    return CodegenReasoner(kwargs.get("llm_client"))


# 预注册（模块加载时执行）
_register_chat_mode()
_register_codegen_mode()
