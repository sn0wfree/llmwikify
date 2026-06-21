"""Phase 15 — AgentRunner abstract base class (borrowed from nanobot v0.2.1).

借鉴 nanobot v0.2.1 ``nanobot/agent/runner.py`` (~700 LOC) 的设计：

  - ``AgentRunner.run(spec: AgentRunSpec) -> AgentRunResult`` — 纯函数式共享
    执行器，**任何**需要"agent loop"的模块都可以调用，与具体实现解耦
  - ``AgentRunner.run_stream(spec) -> AsyncIterator[event]`` — 流式入口
  - ``AgentRunner.wants_streaming() -> bool`` — capability check

设计原则：

  - **鸭子类型 / Generic** — ``AgentRunner`` 不强制 spec / result 是某个具体类型，
    子类可以自由选择 spec dataclass（``ChatRunSpec`` / ``WorkflowSpec`` / ``CronSpec``）。
    通过 ``TypeVar`` 让 ``run_stream`` / ``run_to_completion`` 在子类里自然绑型。
  - **最小契约** — ABC 只暴露 3 个方法 + 1 个 capability check；具体的
    hook / microcompact / consolidate 子类自己实现。
  - **零侵入** — ``ChatRunnerV2`` 加一个继承声明即可，行为完全不变。
  - **可测** — 写一个 ``FakeAgentRunner`` 在 tests 里走完整 spec / result 协议，
    验证 SubagentManager / future CronSkill / future WorkflowActor 都能用。

**本期范围**：

  1. ``AgentRunner`` ABC + 2 个 ``TypeVar``
  2. ``ChatRunnerV2`` 继承 ``AgentRunner[ChatRunSpec, ChatRunResult]``
  3. 不动 ``SubagentManager``（它内部 ``new ChatRunnerV2`` 复用 parent collaborators，
     改基类会丢私有引用 — 留给后续 Phase 16+ 真接基类时再迁）

未做（不在本期范围）：

  - SubagentManager 真接基类 — 后续 Phase：要求 ``AgentRunner`` spec 自带 collaborators，
    或改用 builder pattern
  - ``WorkflowActor`` / ``CronSkill`` 复用 — 后续 Phase
  - Provider / Tool registry 抽进 ABC — 后续 Phase
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Generic, TypeVar

# TypeVars: subclasses bind concrete spec/result types.
# Default to ``Any`` so callers that don't parameterize (rare) still work.
SpecT = TypeVar("SpecT", bound=Any, contravariant=True)
ResultT = TypeVar("ResultT", bound=Any, covariant=True)


class AgentRunner(ABC, Generic[SpecT, ResultT]):
    """Shared abstract base for any "agent loop" executor.

    Mirrors nanobot v0.2.1 ``AgentRunner.run(AgentRunSpec) -> AgentRunResult``
    but kept llmwikify-specific:

      - **Generic** — subclasses bind their own spec / result dataclasses
        (``ChatRunnerV2`` binds ``ChatRunSpec`` / ``ChatRunResult``).
      - **Capability check** — ``wants_streaming()`` mirrors nanobot
        ``_LoopHook.wants_streaming()`` so channel adapters can decide
        whether to consume ``run_stream`` or just ``run_to_completion``.
      - **Async-safe** — all methods are coroutines; subclasses should
        NOT hold cross-call mutable state on ``self``.

    Subclasses MUST implement:

      - ``run_stream(spec) -> AsyncIterator[dict]`` — stream events;
        the terminal event must have ``type == "done"`` (or ``"error"``).
      - ``run_to_completion(spec) -> ResultT`` — drain ``run_stream`` and
        return a typed result dataclass.

    Subclasses MAY override:

      - ``wants_streaming()`` — default returns ``False``; subclasses
        that actually stream should return ``True``.

    Subclasses MUST NOT raise from ``run_to_completion`` for in-loop
    recoverable errors (timeouts, runner errors); instead, populate
    ``ResultT.error`` / ``stop_reason`` and return. Only ``asyncio.CancelledError``
    is allowed to propagate.
    """

    # ── core contract ────────────────────────────────────────

    @abstractmethod
    async def run_stream(self, spec: SpecT) -> AsyncIterator[dict[str, Any]]:
        """Stream events for *spec*. Final event is ``{"type": "done", ...}``.

        The yielded event shape is implementation-defined; the consumer
        (channel adapter) is responsible for filtering. The minimum
        vocabulary expected by the rest of llmwikify is:

          - ``{"type": "done", "content": ..., "stop_reason": ...}``
          - ``{"type": "error", "message": ...}``
          - plus the runner's own internal events (delta / tool_call /
            thinking / etc.)

        Implementations SHOULD NOT raise from ``run_stream`` for
        recoverable errors; convert to ``{"type": "error"}`` events
        and ``return``.
        """
        # Make this an async generator signature via raise NotImplementedError;
        # ABC can't enforce async generator typing directly.
        raise NotImplementedError
        yield {}  # pragma: no cover  — makes this a generator-like stub

    @abstractmethod
    async def run_to_completion(self, spec: SpecT) -> ResultT:
        """Drain ``run_stream`` and return a typed result.

        MUST NOT raise for recoverable errors. Implementations should
        translate stream errors into ``ResultT.error`` / ``stop_reason``
        and return normally.

        MUST raise :class:`asyncio.CancelledError` if the task is
        cancelled (subprocess / channel disconnect).
        """
        raise NotImplementedError

    # ── capability check ──────────────────────────────────────

    def wants_streaming(self) -> bool:
        """Whether this runner actually streams (vs returning a single result).

        Default ``False`` (subclass may override). Channel adapters use
        this to decide whether to consume ``run_stream`` or just call
        ``run_to_completion`` once.

        Mirrors ``nanobot/agent/hook.py:wants_streaming()`` capability
        flag, but at the runner level instead of the hook level — so
        a non-streaming ``FakeAgentRunner`` (test stub) doesn't need
        to implement streaming at all.
        """
        return False

    # ── introspection ────────────────────────────────────────

    @property
    def name(self) -> str:
        """Runner class name for logging / ``/api/health`` introspection.

        Default returns ``type(self).__name__``. Subclasses rarely
        need to override.
        """
        return type(self).__name__


__all__ = ["AgentRunner", "SpecT", "ResultT"]
