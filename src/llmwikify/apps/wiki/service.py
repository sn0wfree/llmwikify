"""WikiService — orchestration layer for wiki operations.

WikiService manages the lifecycle of wiki-related subsystems:

  - Dream proposals (run/approve/reject/apply)
  - Notifications (list/mark_read)
  - Confirmations (list/approve/reject/batch)
  - Scheduler (tick/add/remove tasks)
  - Ingest audit trail (query)
  - Agent status (aggregation)
  - Multi-wiki registry (list/switch/register/unregister/scan)
  - LLM lazy init + config

It does NOT duplicate wiki CRUD operations. Those are
provided by:

  - WikiToolRegistry (tool calling, 21 tools)
  - WikiQuerySkill (Skill framework, 28 actions)

Design ref: ``v0.32-execution-plan.md`` Phase 13d
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WikiService:
    """Orchestration layer for wiki operations.

    Manages dream proposals, notifications, confirmations,
    scheduler, ingest audit, agent status, multi-wiki registry,
    and LLM lifecycle. Does NOT duplicate wiki CRUD.

    Args:
        wiki_registry: The WikiRegistry instance for multi-wiki.
        data_dir: Data directory (typically ``~/.llmwikify/agent/``).
        db: ChatDatabase instance for persistence.
    """

    def __init__(
        self,
        wiki_registry: Any,
        data_dir: Path,
        db: Any,  # ChatDatabase
    ):
        self.wiki_registry = wiki_registry
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = db

        # Lazy-initialized subsystem managers (per wiki)
        self._dream_editors: dict[str, Any] = {}
        self._notification_managers: dict[str, Any] = {}
        self._schedulers: dict[str, Any] = {}
        self._tool_registries: dict[str, Any] = {}

        # LLM lazy init
        self._llm = None
        self._config_manager = None

    # ─── Wiki resolution ─────────────────────────────────────────

    def get_default_wiki_id(self) -> str | None:
        return self.wiki_registry.get_default_wiki_id()

    def get_wiki(self, wiki_id: str | None = None) -> Any:
        if wiki_id:
            return self.wiki_registry.get_wiki(wiki_id)
        return self.wiki_registry.get_default_wiki()

    # ─── LLM ─────────────────────────────────────────────────────

    def get_llm(self) -> Any:
        """Lazy-create the LLM client from config."""
        if self._llm is None:
            from llmwikify.apps.agent.core.config_manager import (
                get_global_config_manager,
            )

            if self._config_manager is None:
                self._config_manager = get_global_config_manager(
                    lambda: self
                )
            default_id = self.get_default_wiki_id()
            wiki_root = None
            if default_id:
                wiki_instance = self.wiki_registry.get_wiki_instance(
                    default_id
                )
                if wiki_instance and wiki_instance.root:
                    wiki_root = wiki_instance.root
            config = self._config_manager.load_effective_llm_config(
                wiki_root
            )
            from llmwikify.apps.chat.providers.registry import create_llm

            self._llm = create_llm(config)
        return self._llm

    def reload_llm(self) -> None:
        """Clear cached LLM so it reloads on next request."""
        self._llm = None

    # ─── Factory methods ─────────────────────────────────────────

    def _get_dream_editor(self, wiki_id: str | None = None) -> Any:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._dream_editors:
            from llmwikify.apps.agent.dream_editor import DreamEditor

            wiki = self.get_wiki(wiki_id)
            self._dream_editors[wiki_id] = DreamEditor(
                wiki=wiki,
                data_dir=self.data_dir / wiki_id,
                db=self.db,
                wiki_id=wiki_id,
            )
        return self._dream_editors[wiki_id]

    def _get_notification_manager(
        self, wiki_id: str | None = None
    ) -> Any:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._notification_managers:
            from llmwikify.apps.agent.notifications import (
                NotificationManager,
            )

            self._notification_managers[wiki_id] = NotificationManager(
                max_size=100,
                db=self.db,
                wiki_id=wiki_id,
            )
        return self._notification_managers[wiki_id]

    def _get_scheduler(self, wiki_id: str | None = None) -> Any:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._schedulers:
            from llmwikify.apps.agent.scheduler import WikiScheduler

            wiki = self.get_wiki(wiki_id)
            scheduler_dir = self.data_dir / wiki_id / "scheduler"
            scheduler_dir.mkdir(parents=True, exist_ok=True)
            scheduler = WikiScheduler(scheduler_dir)
            dream_editor = self._get_dream_editor(wiki_id)
            nm = self._get_notification_manager(wiki_id)
            scheduler.register_system_tasks(wiki, dream_editor, nm)
            scheduler.load_state()
            self._schedulers[wiki_id] = scheduler
        return self._schedulers[wiki_id]

    def get_tool_registry(self, wiki_id: str | None = None) -> Any:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            raise ValueError("No wiki_id available")
        if wiki_id not in self._tool_registries:
            from llmwikify.apps.agent.tools import WikiToolRegistry

            wiki = self.get_wiki(wiki_id)
            self._tool_registries[wiki_id] = WikiToolRegistry(
                wiki, self.db, wiki_id
            )
        return self._tool_registries[wiki_id]

    # ─── Dream (7 methods) ───────────────────────────────────────

    async def run_dream(self, wiki_id: str | None = None) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        editor = self._get_dream_editor(wiki_id)
        result = editor.run_dream()
        if result.get("pending_review", 0) > 0:
            nm = self._get_notification_manager(wiki_id)
            nm.add(
                "info",
                f"Dream generated {result['pending_review']} proposals for review",
                data=result,
            )
        return result

    def get_dream_log(
        self, wiki_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return []
        editor = self._get_dream_editor(wiki_id)
        return editor.get_edit_log(limit)

    def get_dream_proposals(
        self, wiki_id: str | None = None
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {"proposals": {}, "stats": {}}
        editor = self._get_dream_editor(wiki_id)
        return {
            "proposals": editor.proposal_manager.get_pending_by_page(),
            "stats": editor.proposal_manager.get_stats(),
        }

    def approve_proposal(self, proposal_id: str) -> dict:
        for editor in self._dream_editors.values():
            p = editor.proposal_manager.approve(proposal_id)
            if p:
                return p
        return {"status": "error", "error": "Proposal not found"}

    def reject_proposal(self, proposal_id: str) -> dict:
        for editor in self._dream_editors.values():
            p = editor.proposal_manager.reject(proposal_id)
            if p:
                return p
        return {"status": "error", "error": "Proposal not found"}

    def batch_approve_proposals(self, proposal_ids: list[str]) -> dict:
        results = []
        for pid in proposal_ids:
            r = self.approve_proposal(pid)
            results.append(r)
        return {"approved": len(results), "results": results}

    async def apply_proposals(
        self,
        wiki_id: str | None = None,
        proposal_ids: list[str] | None = None,
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        editor = self._get_dream_editor(wiki_id)
        result = editor.apply_proposals(proposal_ids)
        if result.get("applied", 0) > 0:
            nm = self._get_notification_manager(wiki_id)
            nm.add(
                "success",
                f"Applied {result['applied']} dream proposals",
                data=result,
            )
        return result

    # ─── Notifications (2 methods) ───────────────────────────────

    def list_notifications(
        self, wiki_id: str | None = None, unread_only: bool = False
    ) -> list[dict]:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return []
        nm = self._get_notification_manager(wiki_id)
        if unread_only:
            return nm.list_unread()
        return nm.list_all()

    def mark_notification_read(self, notification_id: str) -> dict:
        for nm in self._notification_managers.values():
            if nm.mark_read(notification_id):
                return {"status": "ok", "notification_id": notification_id}
        return {"status": "error", "error": "Notification not found"}

    # ─── Confirmations (5 methods) ───────────────────────────────

    def list_confirmations(
        self, wiki_id: str | None = None
    ) -> dict[str, list[dict]]:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {}
        registry = self.get_tool_registry(wiki_id)
        return registry.get_pending_by_group()

    async def approve_confirmation(
        self,
        confirmation_id: str,
        wiki_id: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        registry = self.get_tool_registry(wiki_id)
        return registry.confirm_execution(
            confirmation_id, arguments=arguments
        )

    async def reject_confirmation(
        self, confirmation_id: str, wiki_id: str | None = None
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {"status": "error", "error": "No wiki_id available"}
        registry = self.get_tool_registry(wiki_id)
        return registry.reject_execution(confirmation_id)

    async def batch_approve_confirmations(
        self,
        confirmation_ids: list[str],
        wiki_id: str | None = None,
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        results = []
        for cid in confirmation_ids:
            r = await self.approve_confirmation(cid, wiki_id)
            results.append(r)
        return {"approved": len(results), "results": results}

    # ─── Ingest audit (2 methods) ────────────────────────────────

    def get_ingest_log(
        self, wiki_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return []
        return self.db.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self.db.get_ingest_entry(ingest_id)

    # ─── Status (1 method) ───────────────────────────────────────

    def get_agent_status(
        self, wiki_id: str | None = None
    ) -> dict:
        wiki_id = wiki_id or self.get_default_wiki_id()
        if not wiki_id:
            return {
                "state": "idle",
                "scheduler_tasks": [],
                "pending_confirmations": 0,
                "dream_proposals": {},
                "unread_notifications": 0,
            }

        scheduler = self._get_scheduler(wiki_id)
        tasks = scheduler.list_tasks()

        editor = self._get_dream_editor(wiki_id)
        dream_stats = editor.proposal_manager.get_stats()

        nm = self._get_notification_manager(wiki_id)
        unread = nm.unread_count()

        registry = self.get_tool_registry(wiki_id)
        pending_confs = len(registry.get_pending_confirmations())

        return {
            "state": "idle",
            "scheduler_tasks": tasks,
            "pending_work": {},
            "action_log": [],
            "pending_confirmations": pending_confs,
            "dream_proposals": dream_stats,
            "unread_notifications": unread,
        }

    # ─── Multi-wiki registry (5 methods) ─────────────────────────

    def list_wikis(self) -> list[dict]:
        wikis = self.wiki_registry.list_wikis()
        return [w.to_dict() for w in wikis]

    def switch_wiki(self, wiki_id: str) -> dict:
        try:
            instance = self.wiki_registry.get_wiki_instance(wiki_id)
            return {
                "message": f"Switched to wiki: {instance.name}",
                "wiki": instance.to_dict(),
            }
        except KeyError:
            return {"error": f"Wiki not found: {wiki_id}"}

    def register_wiki(
        self,
        wiki_id: str,
        name: str,
        wiki_type: str = "local",
        root: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        try:
            if wiki_type == "remote":
                if not url:
                    return {"error": "url required for remote wiki"}
                instance = self.wiki_registry.register_remote(
                    wiki_id=wiki_id, name=name, url=url, api_key=api_key
                )
            else:
                if not root:
                    return {"error": "root required for local wiki"}
                instance = self.wiki_registry.register_wiki(
                    wiki_id=wiki_id, name=name, root=Path(root)
                )
            return {
                "message": f"Registered wiki: {wiki_id}",
                "wiki": instance.to_dict(),
            }
        except Exception as e:
            return {"error": f"register failed: {e!r}"}

    def unregister_wiki(self, wiki_id: str) -> dict:
        try:
            self.wiki_registry.unregister_wiki(wiki_id)
            return {"message": f"Unregistered wiki: {wiki_id}"}
        except KeyError:
            return {"error": f"Wiki not found: {wiki_id}"}

    def scan_wikis(
        self, scan_paths: str = ".", scan_depth: int = 2
    ) -> dict:
        paths = [p.strip() for p in scan_paths.split(",")]
        new_wikis = self.wiki_registry.scan_directories(paths, scan_depth)
        return {
            "new_wikis": [w.to_dict() for w in new_wikis],
            "count": len(new_wikis),
        }
