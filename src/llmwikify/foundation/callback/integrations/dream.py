"""DreamSyncHook — flag a pending dream after Sink-related tool calls."""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.foundation.callback.composite import AgentHook
from llmwikify.foundation.callback.context import AgentHookContext

logger = logging.getLogger(__name__)


class DreamSyncHook(AgentHook):
    name = "dream_sync"

    def __init__(self, dream_editor: Any | None = None) -> None:
        self.dream_editor = dream_editor
        self.pending_dream = False

    def after_tool_executed(
        self, ctx: AgentHookContext, tool_call: Any, result: Any,
    ) -> None:
        if tool_call.name not in {"wiki_synthesize", "wiki_sink_status"}:
            return
        if getattr(result, "success", False):
            self.pending_dream = True

    def check_and_run_dream(self) -> bool:
        if not self.pending_dream or self.dream_editor is None:
            return False
        self.pending_dream = False
        try:
            self.dream_editor.run_dream()
            return True
        except Exception:
            logger.exception("Dream sync failed")
            return False
