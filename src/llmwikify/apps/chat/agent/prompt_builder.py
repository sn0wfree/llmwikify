"""PromptBuilder — system prompt composition for chat.

Extracted from ChatService (v0.41) to separate prompt construction
from the agent loop and tool execution.

Composes 6 sections:
  1. Role + tool usage policy + ReAct pattern
  2. Wiki context
  3. User preferences
  4. Available tools
  5. Current date
  6. Related past conversations
"""

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any

from llmwikify.apps.chat.agent._error_logging import log_exception_returning
from llmwikify.apps.chat.agent.chat_react import REACT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Default user_id for chat-layer preferences.
DEFAULT_USER_ID = "default"


class PromptBuilder:
    """Builds the system prompt from multiple sections."""

    def __init__(self, wiki_service: Any, memory_manager: Any = None):
        self.wiki_service = wiki_service
        self.memory_manager = memory_manager

    async def build(
        self,
        wiki_id: str | None = None,
        user_message: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build the complete system prompt."""
        parts: list[str] = []
        # 1. Role + policy + ReAct reasoning pattern
        parts.append(
            "You are a helpful wiki assistant. You have access "
            "to wiki tools.\n"
            + REACT_SYSTEM_PROMPT
            + "\nWhen a user asks to write, modify, or create wiki "
            "pages, you MUST request confirmation first."
        )
        # 2. Wiki context
        if wiki_id:
            parts.append(f"## Current wiki context\n{wiki_id}")
        # 3. User preferences
        prefs_section = await self._preferences_section()
        if prefs_section:
            parts.append(prefs_section)
        # 4. Available tools
        tools_section = await self._tools_section()
        if tools_section:
            parts.append(tools_section)
        # 4b. Skill commands pointer
        parts.append(
            "When a user types a slash command (e.g. /study) or a "
            "Chinese trigger (e.g. 研究：...), first call "
            "`get_skill_commands` to discover available commands "
            "and their usage, then call the appropriate skill tool."
        )
        # 5. Current date
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        parts.append(f"## Today's date (UTC)\n{today}")
        # 6. Related past conversations
        if user_message and session_id:
            related_section = await self._related_section(
                user_message, session_id,
            )
            if related_section:
                parts.append(related_section)
        return "\n\n".join(parts)

    @staticmethod
    def parse_wiki_prefix(message: str) -> tuple[str | None, str]:
        """Parse @wiki_id prefix from message."""
        match = re.match(r"^@(\S+)\s+(.*)$", message, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, message

    @log_exception_returning(default=None, msg="Failed to load user preferences")
    async def _preferences_section(self) -> str | None:
        """Inject user preferences as a prompt section."""
        if self.memory_manager is None:
            return None
        prefs = await self.memory_manager.preferences.aall(
            DEFAULT_USER_ID,
        )
        if not prefs:
            return None
        parts: list[str] = []
        # Render system_prompt as its own section
        if "system_prompt" in prefs and prefs["system_prompt"]:
            parts.append("## Custom instructions\n" + str(prefs["system_prompt"]))
        # Render other preferences as a markdown list
        other_prefs = {k: v for k, v in prefs.items() if k != "system_prompt"}
        if other_prefs:
            lines = ["## User preferences"]
            for k, v in other_prefs.items():
                lines.append(f"- **{k}**: {v}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts) if parts else None

    @log_exception_returning(default=None, msg="Failed to list tool names")
    async def _tools_section(self) -> str | None:
        """Build a section listing available tools for the prompt."""
        if not hasattr(self.wiki_service, "list_tool_names"):
            return None
        tool_names = self.wiki_service.list_tool_names()
        if not tool_names:
            return None
        return (
            "## Available tools\n"
            + ", ".join(f"`{n}`" for n in tool_names[:20])
            + (f" (+{len(tool_names) - 20} more)" if len(tool_names) > 20 else "")
        )

    @log_exception_returning(default=None, msg="Failed to search related conversations")
    async def _related_section(
        self,
        user_message: str,
        session_id: str,
    ) -> str | None:
        """Surface top-K related past conversations as a prompt section."""
        if self.memory_manager is None:
            return None
        results = await self.memory_manager.index.asearch(
            user_message, session_id=session_id, limit=3,
        )
        if not results:
            return None
        lines = ["## Related past conversations"]
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            if len(content) > 200:
                content = content[:200] + "…"
            source = r.get("source", "unknown")
            lines.append(f"{i}. [{source}] {content}")
        return "\n".join(lines)
