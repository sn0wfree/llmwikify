"""AutoIngestHook — track new files in a wiki raw/ directory."""

from __future__ import annotations

from typing import Any

from llmwikify.foundation.callback.composite import AgentHook
from llmwikify.foundation.callback.context import AgentHookContext


class AutoIngestHook(AgentHook):
    name = "auto_ingest"

    def __init__(self, wiki: Any) -> None:
        self.wiki = wiki
        self._known_files: set[str] = set()
        self._scan_initial()

    def _scan_initial(self) -> None:
        raw_dir = getattr(self.wiki, "raw_dir", None)
        if raw_dir is None or not raw_dir.exists():
            return
        root = self.wiki.root
        self._known_files = {
            str(f.relative_to(root))
            for f in raw_dir.rglob("*")
            if f.is_file()
        }

    def check_new_files(self) -> list[str]:
        raw_dir = getattr(self.wiki, "raw_dir", None)
        if raw_dir is None or not raw_dir.exists():
            return []
        root = self.wiki.root
        current_files = {
            str(f.relative_to(root))
            for f in raw_dir.rglob("*")
            if f.is_file()
        }
        new_files = current_files - self._known_files
        if new_files:
            self._known_files = current_files
        return sorted(new_files)

    def before_iteration(self, ctx: AgentHookContext) -> None:
        self.check_new_files()
