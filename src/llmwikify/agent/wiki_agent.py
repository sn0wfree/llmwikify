"""WikiAgent - Main Agent class that orchestrates all Agent components.

Usage:
    from llmwikify.agent import WikiAgent

    agent = WikiAgent(root="~/wiki")
    await agent.chat("帮我分析这个文件")
    await agent.start()  # Start background scheduler
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from ..core import Wiki
from .dream_editor import DreamEditor
from .hooks import AutoIngestHook, CompositeHook, DreamSyncHook, WikiHook
from .memory import MemoryManager
from .notifications import NotificationManager
from .runner import AgentRunner, RunState, ToolCall
from .scheduler import WikiScheduler
from .tools import WikiToolRegistry

logger = logging.getLogger(__name__)


class WikiAgent:
    """Main wiki agent that orchestrates autonomous wiki maintenance.

    Wraps existing Wiki instance with:
    - Agent runner for execution
    - Tool registry for wiki operations
    - Scheduler for periodic tasks
    - Dream editor for surgical wiki edits
    - Memory manager for conversation/sink history
    - Hooks for lifecycle events
    """

    def __init__(
        self,
        root: str | Path | None = None,
        wiki: Wiki | None = None,
        config: dict | None = None,
        data_dir: str | Path | None = None,
        llm_client: Any | None = None,
    ):
        if wiki is not None:
            self.wiki = wiki
        elif root is not None:
            self.wiki = Wiki(Path(root).resolve(), config=config)
        else:
            raise ValueError("Either 'wiki' or 'root' must be provided")

        self.root = self.wiki.root
        self.data_dir = Path(data_dir) if data_dir else self.root / ".llmwikify" / "agent"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.tool_registry = WikiToolRegistry(self.wiki)
        self.runner = AgentRunner(self.wiki, self.tool_registry)
        self.scheduler = WikiScheduler(self.data_dir)
        self.dream_editor = DreamEditor(self.wiki, self.data_dir)
        self.memory = MemoryManager(self.wiki, self.data_dir)
        self.notifications = NotificationManager()

        self.hooks = CompositeHook()
        self.hooks.add(WikiHook(self.wiki))
        self.hooks.add(DreamSyncHook(self.dream_editor))
        self.hooks.add(AutoIngestHook(self.wiki))

        self._register_runner_hooks()

        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._notification_callbacks: list[Callable] = []

        self.scheduler.register_system_tasks(self.wiki, self.dream_editor, self.notifications)
        self.scheduler.load_state()

    def _register_runner_hooks(self) -> None:
        self.runner.register_hook("pre_run", self.hooks.fire_pre_run)
        self.runner.register_hook("post_run", self.hooks.fire_post_run)
        self.runner.register_hook("pre_tool", self.hooks.fire_pre_tool)
        self.runner.register_hook("post_tool", self.hooks.fire_post_tool)
        self.runner.register_hook("on_confirmation", self.hooks.fire_confirmation)
        self.runner.register_hook("on_error", self.hooks.fire_error)

    async def chat(self, message: str) -> dict:
        """Process a chat message and return agent response.

        Args:
            message: User message

        Returns:
            Dict with response and any pending actions
        """
        self.memory.store_conversation("user", message)

        messages = [{"role": "user", "content": message}]
        result = await self.runner.run(messages)

        self.memory.store_conversation("assistant", str(result))

        return {
            "state": result.state.value,
            "messages": [
                {"role": m.role, "content": m.content} for m in result.messages
            ],
            "actions": result.actions,
            "confirmation_pending": result.confirmation_pending,
            "error": result.error,
        }

    async def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a specific tool call.

        Args:
            tool_name: Tool name (e.g., "wiki_read_page")
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        tool_call = ToolCall(name=tool_name, arguments=arguments)
        result = await self.runner.execute_tool(tool_call)
        return {
            "tool": result.tool_name,
            "success": result.success,
            "result": result.result,
            "error": result.error,
        }

    async def confirm_action(self, confirmation_id: str) -> dict:
        """Confirm a pending action by confirmation ID and execute it.

        Args:
            confirmation_id: The confirmation ID to approve

        Returns:
            Execution result
        """
        result = await self.runner.confirm_action(confirmation_id)
        return {
            "tool": result.tool_name,
            "success": result.success,
            "result": result.result,
            "error": result.error,
        }

    async def confirm_batch(self, confirmation_ids: list[str]) -> list[dict]:
        """Confirm and execute multiple pending actions.

        Args:
            confirmation_ids: List of confirmation IDs to approve

        Returns:
            List of execution results
        """
        results = await self.runner.confirm_batch(confirmation_ids)
        return [
            {
                "tool": r.tool_name,
                "success": r.success,
                "result": r.result,
                "error": r.error,
            }
            for r in results
        ]

    def get_pending_confirmations(self) -> dict:
        """Get all pending confirmations grouped by page type."""
        return {
            "confirmations": self.runner.get_pending_by_group(),
            "total": len(self.runner.get_pending_confirmations()),
        }

    def get_dream_proposals(self) -> dict:
        """Get all pending Dream proposals grouped by page."""
        return {
            "proposals": self.dream_editor.get_proposals_by_page(),
            "stats": self.dream_editor.proposal_manager.get_stats(),
        }

    async def apply_dream_proposals(self, proposal_ids: list[str] | None = None) -> dict:
        """Apply approved Dream proposals to wiki files.

        Args:
            proposal_ids: List of proposal IDs to apply. None = apply all approved.

        Returns:
            Apply results
        """
        return self.dream_editor.apply_proposals(proposal_ids)

    async def start(self, tick_interval: int = 60) -> None:
        """Start the background scheduler loop.

        Args:
            tick_interval: Seconds between scheduler ticks
        """
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(tick_interval))

    async def stop(self) -> None:
        """Stop the background scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        self.scheduler.save_state()

    async def _scheduler_loop(self, interval: int) -> None:
        while self._running:
            try:
                results = self.scheduler.tick()
                for result in results:
                    if result.get("success"):
                        self._notify("task_completed", result)
                    else:
                        self._notify("task_failed", result)

                new_files = self._check_new_files()
                if new_files:
                    self._notify("new_files_detected", {"files": new_files})

                dream_ran = self._check_dream_sync()
                if dream_ran:
                    self._notify("dream_completed", {})

                self.scheduler.save_state()
            except Exception as e:
                logger.error(f"Scheduler tick failed: {e}")

            await asyncio.sleep(interval)

    def _check_new_files(self) -> list[str]:
        for hook in self.hooks._hooks:
            if isinstance(hook, AutoIngestHook):
                return hook.check_new_files()
        return []

    def _check_dream_sync(self) -> bool:
        for hook in self.hooks._hooks:
            if isinstance(hook, DreamSyncHook):
                return hook.check_and_run_dream()
        return False

    def on_notification(self, callback: Callable) -> None:
        self._notification_callbacks.append(callback)

    def _notify(self, event: str, data: dict) -> None:
        type_map = {
            "task_completed": "success",
            "task_failed": "error",
            "new_files_detected": "info",
            "dream_completed": "success",
        }
        self.notifications.add(
            event_type=type_map.get(event, "info"),
            message=f"{event}: {data}",
            data=data,
        )
        for callback in self._notification_callbacks:
            try:
                callback(event, data)
            except Exception as e:
                logger.warning(f"Notification callback failed: {e}")

    def get_status(self) -> dict:
        return {
            "state": self.runner.state.value,
            "scheduler_tasks": self.scheduler.list_tasks(),
            "pending_work": self.memory.get_pending_work(),
            "action_log": self.runner.get_action_log(),
            "recent_history": self.memory.get_context(),
            "recent_edits": self.dream_editor.get_edit_log(),
            "pending_confirmations": len(self.runner.get_pending_confirmations()),
            "dream_proposals": self.dream_editor.proposal_manager.get_stats(),
            "unread_notifications": self.notifications.unread_count(),
        }

    def get_tools(self) -> list[dict]:
        return self.tool_registry.list_tools()

    def get_ingest_log(self, limit: int = 20) -> list[dict]:
        """Get recent ingest log entries."""
        return self.tool_registry.get_ingest_log(limit)
