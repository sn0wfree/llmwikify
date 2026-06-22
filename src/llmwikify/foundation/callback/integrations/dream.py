"""WikiDreamSyncHook — flag a pending wiki dream after Sink-related tool calls."""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.foundation.callback.composite import AgentHook
from llmwikify.foundation.callback.context import AgentHookContext

logger = logging.getLogger(__name__)


class WikiDreamSyncHook(AgentHook):
    name = "wiki_dream_sync"

    def __init__(self, wiki_dream_editor: Any | None = None) -> None:
        self.wiki_dream_editor = wiki_dream_editor
        self.pending_wiki_dream = False

    def after_tool_executed(
        self, ctx: AgentHookContext, tool_call: Any, result: Any,
    ) -> None:
        if tool_call.name not in {"wiki_synthesize", "wiki_sink_status"}:
            return
        if getattr(result, "success", False):
            self.pending_wiki_dream = True

    def check_and_run_wiki_dream(self) -> bool:
        if not self.pending_wiki_dream or self.wiki_dream_editor is None:
            return False
        self.pending_wiki_dream = False
        try:
            self.wiki_dream_editor.run_wiki_dream()
            return True
        except Exception:
            logger.exception("Wiki dream sync failed")
            return False
