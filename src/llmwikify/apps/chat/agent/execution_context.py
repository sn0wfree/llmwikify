"""``AgentExecutionContext`` — shared collaborator bundle for any agent loop (Phase 16+).

The 4 collaborators that ``ChatRunnerV2`` (``chat_service``,
``tool_executor``, ``prompt_builder``, ``config``) accepts in
``__init__`` are not chat-specific — they are the *execution
context* any agent loop needs:

  - ``chat_service``  — LLM connectivity (or any callable that
                         bridges to a model)
  - ``tool_executor`` — tool dispatch (or no-op for tool-less agents)
  - ``prompt_builder``— system prompt construction
  - ``config``         — feature flags (max iterations, microcompact,
                         etc.)

Lifting these into a single dataclass lets :class:`SubagentManager`
share the context with a child runner **without reading private
attributes off the parent**, fixing the LSP violation that the
manager previously enforced at runtime (4-field ``hasattr`` check
that rejected any non-``ChatRunnerV2`` :class:`AgentRunner`).

Phase 16+ also opens the door to other ``AgentRunner`` subclasses
(``WorkflowRunner`` / ``CronRunner``) that satisfy the same
``execution_context()`` contract and can be sub-dispatched via
the same manager.

Back-compat: ``ChatRunnerV2.__init__`` accepts **either** the ctx
**or** the legacy individual keyword args (and builds the ctx
internally). Existing call sites need no change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentExecutionContext:
    """Bundle of collaborators shared across an agent loop boundary.

    Attributes:
        chat_service: LLM-connectivity adapter (or no-op stub for
            tool-only agents). Sits behind the ``ChatServiceAdapter``
            Protocol (apps/chat/agent/protocols.py).
        tool_executor: Tool dispatcher. ``None`` for agents that do
            not use tools.
        prompt_builder: System-prompt / message-shape builder.
        config: Free-form feature flags (max iterations, microcompact,
            etc.). ``None`` falls back to ``merge_six_step_config()``
            in ``ChatRunnerV2``.
        memory_manager: Optional memory layer for the loop. ``None``
            disables per-run memory consolidation.
        hook: Optional :class:`AgentHook` for cross-cutting lifecycle
            events. ``None`` is equivalent to ``NoOpHook()``.
    """

    chat_service: Any
    tool_executor: Any
    prompt_builder: Any
    config: dict[str, Any] | None = None
    memory_manager: Any = None
    hook: Any = field(default=None)


__all__ = ["AgentExecutionContext"]
