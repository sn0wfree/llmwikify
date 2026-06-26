"""Unified Agent Loop — 数据结构。

定义所有 mode 共用的 spec / response / result 类型：

- BaseSpec / ChatSpec / CodegenSpec: 输入规格（继承，不用 God Object）
- ReasonResponse: Reasoner 统一输出
- ActResult: Actor 统一输出
- UnifiedResult: Loop 最终输出
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Spec（继承，不用 God Object）─────────────────────────


@dataclass
class BaseSpec:
    """所有 mode 共用的基础字段。"""

    messages: list[dict[str, Any]]
    max_iterations: int = 10
    timeout_seconds: float = 0
    temperature: float = 0.3


@dataclass
class ChatSpec(BaseSpec):
    """Chat mode 专用。"""

    tool_registry: Any = None
    session_id: str = ""
    wiki_id: str | None = None
    workspace: Path | None = None
    microcompact: bool = True
    microcompact_keep_chars: int = 1000
    microcompact_compactable_tools: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "read_file", "exec", "grep", "find_files", "web_search", "web_fetch", "list_dir",
        }),
    )
    hook: Any | None = None  # AgentHook
    goal_active_predicate: Callable[[], bool] | None = None


@dataclass
class CodegenSpec(BaseSpec):
    """Codegen mode 专用。"""

    df: Any = None  # pl.DataFrame
    factor_name: str = ""
    formula_brief: str = ""
    max_repair_rounds: int = 3
    system_prompt: str = ""


# ─── ReasonResponse — Reasoner 输出 ──────────────────────


@dataclass
class ReasonResponse:
    """Reasoner 的统一输出。

    - raw_content: LLM 原始输出文本
    - tool_calls: function-calling 解析结果（Chat 用）
    - code: extract_python 结果（Codegen 用）
    - action: research action name（Research 用）
    - thought: reasoning thought
    - thinking: <thinking> block 内容
    - is_valid: 解析是否成功
    - error: 解析错误
    """

    raw_content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    code: str | None = None
    action: str | None = None
    thought: str = ""
    thinking: str = ""
    is_valid: bool = True
    error: str | None = None


# ─── ActResult — Actor 输出 ──────────────────────────────


@dataclass
class ActResult:
    """Actor 的统一输出。

    - success: 执行是否成功
    - output: 执行结果（tool result / code execution result）
    - error: 错误信息
    - error_kind: 错误分类
    - tool_name: 执行的工具名（Chat 用）
    - code: 执行的代码（Codegen 用）
    - needs_confirmation: 是否需要用户确认（Chat 用）
    - messages_to_inject: 需要注入到 messages 的消息（observe 产物）
    - tool_calls_for_next_round: 下一轮的 tool_calls（Chat 用，空=停止）
    """

    success: bool
    output: Any = None
    error: str | None = None
    error_kind: str = "none"
    tool_name: str = ""
    code: str = ""
    needs_confirmation: bool = False
    messages_to_inject: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_for_next_round: list[dict[str, Any]] = field(default_factory=list)


# ─── UnifiedResult — Loop 最终输出 ───────────────────────


@dataclass
class UnifiedResult:
    """UnifiedAgentLoop 的统一输出。"""

    final_content: str | None = None
    code: str | None = None
    factor_series: Any = None
    stop_reason: str = "completed"
    error: str | None = None
    iterations: int = 0
    tools_used: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    state_trace: list[dict[str, Any]] = field(default_factory=list)
    elapsed_sec: float = 0.0
    compacted_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（兼容 ReactResult.to_dict() 接口）。"""
        return {
            "code": self.code or "",
            "is_valid": self.stop_reason == "completed" and self.error is None,
            "error_kind": "none" if self.error is None else "execute_error",
            "error_message": self.error or "",
            "iterations": self.iterations,
            "steps": self.steps,
            "state_trace": self.state_trace,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "stop_reason": self.stop_reason,
            "final_content_len": len(self.final_content) if self.final_content else 0,
        }
