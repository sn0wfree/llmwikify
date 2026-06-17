"""Hook context — mutable per-iteration state shared across AgentHook invocations.

One AgentHookContext instance is created per Runner.run() call and mutated
in-place as the runner progresses through the agent loop. All registered
hooks receive the same context object, so per-iteration state (tool_calls,
usage, streamed_content flags, etc.) is observable across the fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentHookContext:
    iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    response: Any | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[Any] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    streamed_content: bool = False
    streamed_reasoning: bool = False
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None
