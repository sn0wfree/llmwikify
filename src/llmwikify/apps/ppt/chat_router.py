"""PPTChat Router - Unified message routing.

Routes user input: try deterministic first, fallback to LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncGenerator

from .chat_engine import PPTChatEngine
from .harness import SlideHarness
from .schema import Presentation

logger = logging.getLogger(__name__)

# ─── Deterministic patterns ───────────────────────────────────────

PATTERNS = {
    r"删除(?:第|这)(\d+)(?:页|张|个幻灯片)": "delete_slide",
    r"移除(?:第|这)(\d+)(?:页|张)": "delete_slide",
    r"移动第(\d+)页到第(\d+)": "move_slide",
    r"把第(\d+)页移到第(\d+)": "move_slide",
    r"复制(?:第|这)(\d+)(?:页|张)": "duplicate_slide",
    r"拷贝(?:第|这)(\d+)(?:页|张)": "duplicate_slide",
    r"撤销|回退|上一步|恢复": "undo",
    r"换.*?主题.*?为?\s*(\S+)": "change_theme",
    r"切换.*?主题.*?为?\s*(\S+)": "change_theme",
}

# ─── Number word mapping ──────────────────────────────────────────

CN_NUMS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

def _parse_cn_num(s: str) -> int | None:
    """Parse Chinese number string to int."""
    if s in CN_NUMS:
        return CN_NUMS[s]
    try:
        return int(s)
    except (ValueError, TypeError):
        return None

class PPTChatRouter:
    """Unified message router.

    Tries deterministic pattern matching first (fast, no LLM).
    Falls back to LLM engine for fuzzy intent.
    """

    def __init__(self, llm: Any):
        self.engine = PPTChatEngine(llm=llm)

    async def route(
        self,
        message: str,
        presentation: Presentation,
        current_slide_index: int,
        history: list | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Route user message to appropriate handler.

        Yields events in the same format as PPTChatEngine.
        """
        harness = SlideHarness(presentation)

        # 1. Try deterministic pattern matching
        for pattern, tool_name in PATTERNS.items():
            match = re.search(pattern, message)
            if match:
                result = self._execute_deterministic(
                    tool_name, match, harness, current_slide_index
                )
                if result is not None:
                    yield {
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": {"match": match.group(0)},
                    }
                    yield {
                        "type": "tool_end",
                        "tool": tool_name,
                        "result": {"success": True},
                    }
                    yield {
                        "type": "done",
                        "updated_presentation": result.model_dump(),
                        "message": self._tool_message(tool_name, match),
                    }
                    return

        # 2. Fallback to LLM
        async for event in self.engine.chat(
            message=message,
            presentation=presentation,
            current_slide_index=current_slide_index,
            history=history,
        ):
            yield event

    def _execute_deterministic(
        self,
        tool_name: str,
        match: re.Match,
        harness: SlideHarness,
        current_slide_index: int,
    ) -> Presentation | None:
        """Execute a deterministic tool operation."""
        try:
            if tool_name == "delete_slide":
                idx = _parse_cn_num(match.group(1))
                if idx is None:
                    idx = 1
                return harness.delete_slide(idx - 1)  # 1-indexed to 0-indexed

            elif tool_name == "move_slide":
                from_idx = _parse_cn_num(match.group(1))
                to_idx = _parse_cn_num(match.group(2))
                if from_idx is None or to_idx is None:
                    return None
                return harness.move_slide(from_idx - 1, to_idx - 1)

            elif tool_name == "duplicate_slide":
                idx = _parse_cn_num(match.group(1))
                if idx is None:
                    idx = 1
                return harness.duplicate_slide(idx - 1)

            elif tool_name == "undo":
                return harness.undo()

            elif tool_name == "change_theme":
                theme_id = match.group(1)
                return harness.change_theme(theme_id)

        except Exception as e:
            logger.error(f"Deterministic tool {tool_name} failed: {e}")
            return None

        return None

    def _tool_message(self, tool_name: str, match: re.Match) -> str:
        """Generate a human-readable message for deterministic operations."""
        if tool_name == "delete_slide":
            idx = match.group(1)
            return f"已删除第{idx}页"
        elif tool_name == "move_slide":
            return f"已移动第{match.group(1)}页到第{match.group(2)}页"
        elif tool_name == "duplicate_slide":
            return f"已复制第{match.group(1)}页"
        elif tool_name == "undo":
            return "已撤销上一步操作"
        elif tool_name == "change_theme":
            return f"已切换主题为 {match.group(1)}"
        return "操作已完成"
