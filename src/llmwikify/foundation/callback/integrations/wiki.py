"""WikiHook — append a wiki log entry after wiki-mutating tool calls."""

from __future__ import annotations

from typing import Any

from llmwikify.foundation.callback.composite import AgentHook
from llmwikify.foundation.callback.context import AgentHookContext


class WikiHook(AgentHook):
    name = "wiki"

    def __init__(self, wiki: Any) -> None:
        self.wiki = wiki

    def after_tool_executed(
        self, ctx: AgentHookContext, tool_call: Any, result: Any,
    ) -> None:
        if tool_call.name not in {"wiki_write_page", "wiki_ingest", "wiki_synthesize"}:
            return
        if not getattr(result, "success", False):
            return
        self.wiki.append_log("agent", f"Tool {tool_call.name} executed successfully")
