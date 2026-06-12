"""ToolExecutor — tool call execution and persistence.

Extracted from ChatService (v0.41) to separate tool execution
from the agent loop and prompt construction.

Handles:
  - Tool call execution via registry
  - DB persistence of tool calls and messages
  - MemoryManager context persistence
  - LLM stream retry on first chunk
  - Ingest logging for posthoc-confirmation tools
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls and persists results."""

    def __init__(
        self,
        chat_db: Any,
        memory_manager: Any = None,
        config: dict | None = None,
    ):
        from llmwikify.apps.chat.config import merge_six_step_config
        self.db = chat_db
        self.memory_manager = memory_manager
        self.config = config or merge_six_step_config()
        self._save_error_count: int = 0

        from llmwikify.apps.chat.retry_managers import DBRetryManager
        self._db_retry = DBRetryManager(
            max_attempts=self.config.get("chat_db_retry_max_attempts", 3),
            base_delay=self.config.get("chat_db_retry_base_delay", 0.5),
        )

    async def execute(
        self,
        tool_name: str,
        args: dict,
        tool_registry: Any,
        session_id: str,
        ctx: Any,
    ) -> dict | list:
        """Execute a tool call and persist to DB."""
        call_id = self.db.log_tool_call(session_id, tool_name, args, "pending")
        try:
            result = await tool_registry.execute(tool_name, args)
            status = (
                "confirmation_required"
                if isinstance(result, dict) and result.get("status") == "confirmation_required"
                else "executed"
            )
            self.db.update_tool_call(call_id, result, status)

            tool_def = tool_registry._tools.get(tool_name, {})
            if tool_def.get("requires_confirmation") == "posthoc":
                entry_id = f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                self.db.log_ingest({
                    "id": entry_id,
                    "wiki_id": ctx.wiki_id or "default",
                    "tool": tool_name,
                    "arguments": args,
                    "result_summary": str(result)[:self.config.get("summary_truncate_chars", 500)] if result else "",
                    "status": "executed",
                })

            return result
        except Exception as e:
            self.db.update_tool_call(call_id, {"error": str(e)}, "error")
            return {"status": "error", "error": str(e)}

    async def persist_tool_result(
        self,
        session_id: str,
        tool_name: str,
        args: dict,
        result: Any,
    ) -> None:
        """Persist a tool result to the MemoryManager context store."""
        if self.memory_manager is None:
            return
        try:
            content = json.dumps(
                {"tool": tool_name, "args": args, "result": result},
                ensure_ascii=False, default=str,
            )
            if len(content) > self.config.get("content_truncate_chars", 2000):
                content = content[:self.config.get("content_truncate_chars", 2000)] + "…"
            await self.memory_manager.context.aadd(
                session_id,
                entry_type="tool_result",
                content=content,
                metadata={"tool": tool_name},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to persist tool result to memory.context: %s", e,
            )

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        tokens_reasoning: int = 0,
        tokens_cache_read: int = 0,
        tokens_cache_write: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Persist a chat message with retry."""
        msg = {
            "id": uuid.uuid4().hex,
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "tokens_reasoning": tokens_reasoning,
            "tokens_cache_read": tokens_cache_read,
            "tokens_cache_write": tokens_cache_write,
            "cost": cost,
        }
        try:
            self._db_retry.call(self.db.save_chat_message, msg)
        except Exception as e:
            logger.error("Failed to save chat message for session %s: %s", session_id, e)
            self._save_error_count += 1

    async def llm_stream_with_retry(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        llm_client: Any,
    ) -> AsyncIterator[dict]:
        """Wrap LLM stream with retry on first chunk."""
        from llmwikify.apps.chat.retry_managers import LLMRetryManager
        retry = LLMRetryManager(
            max_attempts=self.config.get("llm_retry_max_attempts", 3),
            base_delay=self.config.get("llm_retry_base_delay", 1.0),
            call_timeout=self.config.get("llm_retry_call_timeout", 30.0),
        )

        last_exc: Exception | None = None
        for attempt in range(retry.max_attempts):
            try:
                first = True
                async for ev in llm_client.astream_chat(messages, tools=tools):
                    first = False
                    yield ev
                return
            except Exception as e:  # noqa: BLE001
                if first:
                    last_exc = e
                    if not retry._is_retriable(e):
                        raise
                    if attempt < retry.max_attempts - 1:
                        delay = min(retry.base_delay * (2 ** attempt), 30.0)
                        logger.warning(
                            "LLM stream failed on attempt %d/%d "
                            "(no chunks produced): %s. Retrying in %.1fs...",
                            attempt + 1, retry.max_attempts, e, delay,
                        )
                        await asyncio.sleep(delay)
                else:
                    raise
        if last_exc:
            raise last_exc

    def get_toolspec(self, tool_registry: Any) -> list[dict[str, Any]]:
        """Build OpenAI-format tool spec from registry."""
        tools = tool_registry.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("parameters", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                },
            }
            for t in tools
        ]
