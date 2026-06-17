"""ChatRunSpec / ChatRunResult — dataclass API for ChatRunner.

Mirrors nanobot v0.2.1 AgentRunSpec / AgentRunResult shape but is
independent of any framework (no loguru, no provider ABC). Phase A
``runner.py`` consumes these; ``chat_react.py`` reads the microcompact
flags from the spec via a callable built by the runner.

Microcompact is **on by default** (2026-06-17 user decision) so the
common case — large ``read_file`` results — saves tokens without any
caller opt-in.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "exec",
    "grep",
    "find_files",
    "web_search",
    "web_fetch",
    "list_dir",
})


@dataclass
class ChatRunSpec:
    messages: list[dict[str, Any]]
    tool_registry: Any
    session_id: str
    wiki_id: str | None = None
    model: str = "MiniMax-M2.7"
    max_iterations: int = 10
    max_tool_result_chars: int = 50000
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    hook: Any | None = None
    error_message: str | None = None
    workspace: Path | None = None
    context_window_tokens: int | None = None
    progress_callback: Callable[..., Any] | None = None
    fail_on_tool_error: bool = False

    microcompact: bool = True
    microcompact_keep_chars: int = 1000
    microcompact_compactable_tools: frozenset[str] = field(
        default_factory=lambda: DEFAULT_COMPACTABLE_TOOLS,
    )

    _compacted_results: dict[str, Any] = field(default_factory=dict)

    def compacted(self) -> list[tuple[str, Any]]:
        return list(self._compacted_results.items())


@dataclass
class ChatRunResult:
    final_content: str | None
    messages: list[dict[str, Any]]
    tools_used: list[str]
    usage: dict[str, int]
    stop_reason: str
    error: str | None = None
    compacted_count: int = 0
    total_compacted_chars_saved: int = 0
