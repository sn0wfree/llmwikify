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
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
        if tool_name not in {"wiki_write_page", "wiki_ingest", "wiki_synthesize"}:
            return
        if isinstance(result, dict):
            success = result.get("success", False)
        else:
            success = getattr(result, "success", False)
        if not success:
            return
        self.wiki.append_log("agent", f"Tool {tool_name} executed successfully")
