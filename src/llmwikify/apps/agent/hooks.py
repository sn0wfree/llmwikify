"""Hooks System - Lifecycle callbacks for Agent events.

Provides hook points for:
- Pre/post run events
- Pre/post tool execution
- Confirmation requests
- Error handling
- Wiki-specific events (DreamSync, AutoIngest)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Hook:
    """Base hook class."""

    name: str = "base"

    def on_pre_run(self, runner: Any, messages: list[dict]) -> None:
        pass

    def on_post_run(self, runner: Any, result: Any) -> None:
        pass

    def on_pre_tool(self, runner: Any, tool_call: Any) -> None:
        pass

    def on_post_tool(self, runner: Any, tool_call: Any, result: Any) -> None:
        pass

    def on_confirmation(self, runner: Any, tool_call: Any) -> None:
        pass

    def on_error(self, runner: Any, error: Exception) -> None:
        pass


class WikiHook(Hook):
    """Hook that logs wiki state changes."""

    name = "wiki"

    def __init__(self, wiki: Any):
        self.wiki = wiki

    def on_post_tool(self, runner: Any, tool_call: Any, result: Any) -> None:
        if tool_call.name in ("wiki_write_page", "wiki_ingest", "wiki_synthesize"):
            if result.success:
                self.wiki.append_log("agent", f"Tool {tool_call.name} executed successfully")


class DreamSyncHook(Hook):
    """Hook that triggers Dream analysis after Sink updates."""

    name = "dream_sync"

    def __init__(self, dream_editor: Any | None = None):
        self.dream_editor = dream_editor
        self.pending_dream = False

    def on_post_tool(self, runner: Any, tool_call: Any, result: Any) -> None:
        if tool_call.name in ("wiki_synthesize", "wiki_sink_status"):
            if result.success:
                self.pending_dream = True

    def check_and_run_dream(self) -> bool:
        if self.pending_dream and self.dream_editor:
            self.pending_dream = False
            try:
                self.dream_editor.run_dream()
                return True
            except Exception as e:
                logger.error(f"Dream sync failed: {e}")
                return False
        return False


class AutoIngestHook(Hook):
    """Hook that monitors raw/ directory for new files."""

    name = "auto_ingest"

    def __init__(self, wiki: Any):
        self.wiki = wiki
        self._known_files: set[str] = set()
        self._scan_initial()

    def _scan_initial(self) -> None:
        if self.wiki.raw_dir.exists():
            self._known_files = {
                str(f.relative_to(self.wiki.root))
                for f in self.wiki.raw_dir.rglob("*")
                if f.is_file()
            }

    def check_new_files(self) -> list[str]:
        if not self.wiki.raw_dir.exists():
            return []
        current_files = {
            str(f.relative_to(self.wiki.root))
            for f in self.wiki.raw_dir.rglob("*")
            if f.is_file()
        }
        new_files = current_files - self._known_files
        if new_files:
            self._known_files = current_files
        return sorted(new_files)


class CompositeHook:
    """Manages multiple hooks and dispatches events."""

    def __init__(self):
        self._hooks: list[Hook] = []

    def add(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def remove(self, name: str) -> None:
        self._hooks = [h for h in self._hooks if h.name != name]

    def fire_pre_run(self, runner: Any, messages: list[dict]) -> None:
        for hook in self._hooks:
            try:
                hook.on_pre_run(runner, messages)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_pre_run failed: {e}")

    def fire_post_run(self, runner: Any, result: Any) -> None:
        for hook in self._hooks:
            try:
                hook.on_post_run(runner, result)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_post_run failed: {e}")

    def fire_pre_tool(self, runner: Any, tool_call: Any) -> None:
        for hook in self._hooks:
            try:
                hook.on_pre_tool(runner, tool_call)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_pre_tool failed: {e}")

    def fire_post_tool(self, runner: Any, tool_call: Any, result: Any) -> None:
        for hook in self._hooks:
            try:
                hook.on_post_tool(runner, tool_call, result)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_post_tool failed: {e}")

    def fire_confirmation(self, runner: Any, tool_call: Any) -> None:
        for hook in self._hooks:
            try:
                hook.on_confirmation(runner, tool_call)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_confirmation failed: {e}")

    def fire_error(self, runner: Any, error: Exception) -> None:
        for hook in self._hooks:
            try:
                hook.on_error(runner, error)
            except Exception as e:
                logger.warning(f"Hook {hook.name} on_error failed: {e}")
