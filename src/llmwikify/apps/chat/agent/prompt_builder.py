"""PromptBuilder — 7-section system prompt composer.

Borrowed from nanobot v0.2.1 ``ContextBuilder`` (see
``docs/poc/nanobot-framework.md`` §2.5 for context) but kept llmwikify
specific: consumes the existing ``wiki_service`` / ``memory_manager``
collaborators instead of a ``MemoryStore`` / ``SkillsLoader`` pair.

Section assembly order (joined by ``\n\n---\n\n``):

  1. Identity         workspace path, OS, Python, today's date
  2. Bootstrap        AGENTS.md / SOUL.md / USER.md (mtime cached)
  3. Tool Contract    tool list + skill-command pointer
  4. Memory           user preferences (from memory_manager)
  5. Skills Summary   always-loaded skills + index
  6. ReAct Prompt     REACT_SYSTEM_PROMPT
  7. Recent History   wiki context + related conversations

Each section is wrapped in a try/except so a single failure degrades
to an empty string instead of breaking the whole prompt.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.agent._error_logging import log_exception_returning
from llmwikify.apps.chat.agent.chat_react import REACT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "default"

BOOTSTRAP_FILES: tuple[str, ...] = ("AGENTS.md", "SOUL.md", "USER.md")
MAX_HISTORY_CHARS = 32_000
DEFAULT_BOOTSTRAP_CACHE_SECONDS = 300


@dataclass(slots=True)
class BuildContext:
    wiki_id: str | None = None
    user_message: str | None = None
    session_id: str | None = None
    workspace: Path | None = None
    channel: str = "chat"
    timezone: str | None = None
    enable_bootstrap: bool = True
    always_skills: list[str] = field(default_factory=list)
    exclude_skills: set[str] = field(default_factory=set)
    max_history_chars: int = MAX_HISTORY_CHARS


class PromptBuilder:
    """Builds the system prompt from multiple sections.

    Backward-compatible: ``build(wiki_id, user_message, session_id)``
    still works; the new typed entry point is
    :meth:`build_with_context` which accepts a :class:`BuildContext`.
    """

    def __init__(
        self,
        wiki_service: Any,
        memory_manager: Any = None,
        workspace: Path | None = None,
        config: dict | None = None,
    ) -> None:
        self.wiki_service = wiki_service
        self.memory_manager = memory_manager
        self.workspace = workspace
        self.config = config or {}
        self._bootstrap_cache: dict[str, tuple[float, float, str]] = {}
        self._bootstrap_cache_ttl = self.config.get(
            "bootstrap_cache_seconds", DEFAULT_BOOTSTRAP_CACHE_SECONDS,
        )

    async def build(
        self,
        wiki_id: str | None = None,
        user_message: str | None = None,
        session_id: str | None = None,
        workspace: Path | None = None,
        enable_bootstrap: bool = True,
    ) -> str:
        """Legacy entry point preserved for callers that pass positional args."""
        ctx = BuildContext(
            wiki_id=wiki_id,
            user_message=user_message,
            session_id=session_id,
            workspace=workspace or self.workspace,
            enable_bootstrap=enable_bootstrap,
        )
        return await self.build_with_context(ctx)

    async def build_with_context(self, ctx: BuildContext) -> str:
        coros = [
            self._safe_section("identity", self._get_identity(ctx)),
        ]
        if ctx.enable_bootstrap:
            coros.append(
                self._safe_section("bootstrap", self._load_bootstrap_files(ctx)),
            )
        else:
            coros.append(_empty())
        coros.extend([
            self._safe_section("tool_contract", self._get_tool_contract(ctx)),
            self._safe_section("memory", self._get_memory_section(ctx)),
            self._safe_section("skills", self._get_skills_section(ctx)),
            self._safe_section("react", self._get_react_prompt(ctx)),
            self._safe_section("history", self._get_recent_history(ctx)),
        ])
        sections = await asyncio.gather(*coros)
        return "\n\n---\n\n".join(s for s in sections if s)

    async def build_minimal(self, ctx: BuildContext) -> str:
        sections = await asyncio.gather(
            self._safe_section("identity", self._get_identity(ctx)),
            self._safe_section("tool_contract", self._get_tool_contract(ctx)),
            self._safe_section("react", self._get_react_prompt(ctx)),
        )
        return "\n\n---\n\n".join(s for s in sections if s)

    async def _safe_section(self, name: str, value: Any) -> str:
        try:
            if asyncio.iscoroutine(value):
                value = await value
            return value or ""
        except Exception:
            logger.warning("Section %s failed", name, exc_info=True)
            return ""

    @staticmethod
    def parse_wiki_prefix(message: str) -> tuple[str | None, str]:
        """Parse ``@wiki_id`` prefix from the start of *message*."""
        match = re.match(r"^@(\S+)\s+(.*)$", message, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return None, message

    def _get_identity(self, ctx: BuildContext) -> str:
        workspace = ctx.workspace or self.workspace
        workspace_path = (
            str(workspace.expanduser().resolve()) if workspace else "(unset)"
        )
        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return (
            "You are a helpful wiki assistant. You have access to wiki tools.\n"
            f"Workspace: {workspace_path}\n"
            f"Runtime: {runtime}\n"
            f"Today's date (UTC): {today}\n"
            "When a user asks to write, modify, or create wiki pages, you "
            "MUST request confirmation first."
        )

    def _load_bootstrap_files(self, ctx: BuildContext) -> str:
        workspace = ctx.workspace or self.workspace
        if workspace is None:
            return ""
        root = Path(workspace).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return ""
        parts: list[str] = []
        for name in BOOTSTRAP_FILES:
            path = root / name
            if not path.is_file():
                continue
            content = self._read_with_cache(path)
            if content:
                parts.append(f"## {name}\n{content}")
        return "\n\n".join(parts)

    def _read_with_cache(self, path: Path) -> str:
        now = time.monotonic()
        cached = self._bootstrap_cache.get(str(path))
        if cached is not None:
            cached_at, mtime_at_cache, text = cached
            if now - cached_at < self._bootstrap_cache_ttl:
                try:
                    current_mtime = path.stat().st_mtime
                    if current_mtime == mtime_at_cache:
                        return text
                except OSError:
                    pass
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        self._bootstrap_cache[str(path)] = (now, mtime, text)
        return text

    @log_exception_returning(default=None, msg="Failed to list tool names")
    def _get_tool_contract(self, ctx: BuildContext) -> str | None:
        sections: list[str] = []
        tool_names: list[str] = []
        if hasattr(self.wiki_service, "list_tool_names"):
            tool_names = list(self.wiki_service.list_tool_names() or [])
        if tool_names:
            tool_list = ", ".join(f"`{n}`" for n in tool_names[:20])
            if len(tool_names) > 20:
                tool_list += f" (+{len(tool_names) - 20} more)"
            sections.append(f"## Available tools\n{tool_list}")
        sections.append(
            "When a user types a slash command (e.g. /study) or a Chinese "
            "trigger (e.g. 研究：...), first call `get_skill_commands` to "
            "discover available commands and their usage, then call the "
            "appropriate skill tool."
        )
        return "\n\n".join(sections)

    @log_exception_returning(default=None, msg="Failed to load user preferences")
    async def _get_memory_section(self, ctx: BuildContext) -> str | None:
        if self.memory_manager is None:
            return None
        prefs = await self.memory_manager.preferences.aall(DEFAULT_USER_ID)
        if not prefs:
            return None
        parts: list[str] = []
        if "system_prompt" in prefs and prefs["system_prompt"]:
            parts.append("## Custom instructions\n" + str(prefs["system_prompt"]))
        other_prefs = {k: v for k, v in prefs.items() if k != "system_prompt"}
        if other_prefs:
            lines = ["## User preferences"]
            for k, v in other_prefs.items():
                lines.append(f"- **{k}**: {v}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts) if parts else None

    async def _get_skills_section(self, ctx: BuildContext) -> str | None:
        if not ctx.always_skills:
            return None
        descriptions: Any = None
        if hasattr(self.wiki_service, "get_skill_descriptions"):
            try:
                descriptions = self.wiki_service.get_skill_descriptions(
                    ctx.always_skills,
                )
            except Exception:
                logger.warning("get_skill_descriptions failed", exc_info=True)
        lines = ["## Active skills"]
        for name in ctx.always_skills:
            if name in ctx.exclude_skills:
                continue
            desc = (descriptions or {}).get(name, "(no description)")
            lines.append(f"- **{name}**: {desc}")
        return "\n".join(lines)

    def _get_react_prompt(self, ctx: BuildContext) -> str:
        return REACT_SYSTEM_PROMPT

    @log_exception_returning(default=None, msg="Failed to compose history")
    async def _get_recent_history(self, ctx: BuildContext) -> str | None:
        parts: list[str] = []
        if ctx.wiki_id:
            parts.append(f"## Current wiki context\n{ctx.wiki_id}")
        if (
            ctx.user_message
            and ctx.session_id
            and self.memory_manager is not None
        ):
            results = await self.memory_manager.index.asearch(
                ctx.user_message, session_id=ctx.session_id, limit=3,
            )
            if results:
                lines = ["## Related past conversations"]
                for i, r in enumerate(results, 1):
                    content = r.get("content", "")
                    if len(content) > 200:
                        content = content[:200] + "…"
                    source = r.get("source", "unknown")
                    lines.append(f"{i}. [{source}] {content}")
                parts.append("\n".join(lines))
        if not parts:
            return None
        joined = "\n\n".join(parts)
        if len(joined) > ctx.max_history_chars:
            joined = joined[: ctx.max_history_chars] + "…"
        return joined


async def _empty() -> str:
    return ""
