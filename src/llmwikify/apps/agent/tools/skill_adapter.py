"""Adapters that expose chat skills as agent tools."""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from llmwikify.apps.chat.skills.base import SkillContext, SkillResult


class SkillToolAdapter:
    def __init__(
        self,
        skill_service: Any,
        wiki: Any = None,
        db: Any = None,
        wiki_id: str | None = None,
        session_id: str = "",
        exposed_skills: list[str] | tuple[str, ...] | None = None,
        wiki_service: Any = None,
        subagent_manager: Any = None,
        child_tool_registry: Any = None,
    ):
        self.skill_service = skill_service
        self.wiki = wiki
        self.db = db
        self.wiki_id = wiki_id
        self.session_id = session_id
        self.wiki_service = wiki_service
        # Phase 10-E (2026-06-20): optional SubagentManager + child
        # tool_registry. When set, ``subagent`` is auto-added to
        # exposed_skills so the LLM can call spawn_subagent. The
        # child_tool_registry MUST NOT contain the subagent tool
        # (caller's responsibility) — children cannot grandchild.
        self.subagent_manager = subagent_manager
        self.child_tool_registry = child_tool_registry
        default_exposed = ["dynamic_workflow", "autoresearch_compound", "web_search", "web_fetch"]
        if subagent_manager is not None:
            default_exposed.append("subagent")
        self.exposed_skills = set(exposed_skills or default_exposed)
        self._name_map: dict[str, tuple[str, str]] = {}
        self._tools: dict[str, dict[str, Any]] = {}
        self._pending_confirmations: dict[str, dict[str, Any]] = {}
        self.skill_service.register_all()
        self._build_tools()
        self._register_get_skill_commands()

    @staticmethod
    def _tool_name(skill_name: str, action_name: str) -> str:
        return f"{skill_name}_{action_name}".replace(".", "_").replace("-", "_")

    @staticmethod
    def _normalize_confirmation(policy: Any) -> bool | str:
        if policy is True:
            return "pre"
        return policy or False

    def _build_tools(self) -> None:
        registry = self.skill_service.registry
        for skill_name, action in registry.all_actions():
            if self.exposed_skills and skill_name not in self.exposed_skills:
                continue
            tool_name = self._tool_name(skill_name, action.name)
            self._name_map[tool_name] = (skill_name, action.name)
            self._tools[tool_name] = {
                "description": action.description,
                "action_type": action.action_type,
                "requires_confirmation": self._normalize_confirmation(action.requires_confirmation),
                "parameters": action.input_schema,
                "output_schema": action.output_schema,
            }

    def _register_get_skill_commands(self) -> None:
        """Register the get_skill_commands tool."""
        from llmwikify.apps.agent.tools import handle_get_skill_commands
        self._tools["get_skill_commands"] = {
            "description": "List all available skill commands and triggers",
            "action_type": "read",
            "requires_confirmation": False,
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
        self._name_map["get_skill_commands"] = ("__builtin__", "get_skill_commands")
        self._get_skill_commands_handler = handle_get_skill_commands

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": info["description"],
                "action_type": info["action_type"],
                "requires_confirmation": info["requires_confirmation"],
                "parameters": info.get("parameters", {"type": "object", "properties": {}, "required": []}),
            }
            for name, info in self._tools.items()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._name_map:
            available = ", ".join(sorted(self._name_map.keys()))
            raise ValueError(f"Unknown skill tool: {name!r}. Available tools: [{available}]")
        # Handle get_skill_commands specially
        if name == "get_skill_commands":
            return await self._get_skill_commands_handler(arguments, None)
        confirmation_mode = self._tools[name].get("requires_confirmation", False)
        if confirmation_mode == "pre":
            # v0.41: short-circuit if user previously clicked "Always"
            # for this tool in this session. Without this, the
            # chat_permissions row written by approve_confirmation()
            # was dead code (db.has_always_permission() had no caller).
            if self.db and self.db.has_always_permission(
                name, session_id=self.session_id,
            ):
                return await self._execute_direct(name, arguments)
            confirmation_id = str(uuid.uuid4())[:8]
            confirmation = {
                "id": confirmation_id,
                "tool": name,
                "arguments": arguments,
                "action_type": self._tools[name].get("action_type", "read"),
                "impact": self._analyze_impact(name, arguments),
                "group": "skill_actions",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            }
            self._pending_confirmations[confirmation_id] = confirmation
            return {
                "status": "confirmation_required",
                "confirmation_id": confirmation_id,
                "impact": confirmation["impact"],
                "group": confirmation["group"],
            }
        result = await self._execute_direct(name, arguments)
        if confirmation_mode == "posthoc":
            return {"status": "executed", "result": result, "posthoc": True}
        return result

    def _analyze_impact(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "change_type": "skill_action",
            "tool": name,
            "skill_action": ".".join(self._name_map[name]),
            "arguments_preview": json.dumps(arguments, ensure_ascii=False, default=str)[:500],
        }

    async def _execute_direct(self, name: str, arguments: dict[str, Any]) -> Any:
        skill_name, action_name = self._name_map[name]
        # Resolve llm_spec from wiki_service
        llm_spec = None
        if self.wiki_service and hasattr(self.wiki_service, "get_llm_spec"):
            try:
                llm_spec = self.wiki_service.get_llm_spec()
            except Exception:
                pass
        config: dict[str, Any] = {"wiki_id": self.wiki_id} if self.wiki_id else {}
        # Phase 10-E (2026-06-20): expose SubagentManager + safe child
        # tool registry to subagent_skill via SkillContext.config.
        if self.subagent_manager is not None:
            config["subagent_manager"] = self.subagent_manager
        if self.child_tool_registry is not None:
            config["child_tool_registry"] = self.child_tool_registry
        ctx = SkillContext(
            wiki=self.wiki,
            db=self.db,
            llm_spec=llm_spec,
            config=config,
            session_id=self.session_id,
        )
        result = self.skill_service.execute(skill_name, action_name, arguments, ctx)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, SkillResult):
            return result.to_dict()
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self._tools.get(name)

    def confirm_execution(self, confirmation_id: str, arguments: dict | None = None) -> Any:
        confirmation = self._pending_confirmations.pop(confirmation_id, None)
        if confirmation is None:
            return {"status": "error", "error": f"Unknown confirmation ID: {confirmation_id}"}
        args = arguments if arguments is not None else confirmation["arguments"]
        try:
            result = self._execute_confirmed(confirmation["tool"], args)
            confirmation["status"] = "approved"
            return {"status": "executed", "confirmation_id": confirmation_id, "result": result}
        except Exception as e:
            confirmation["status"] = "rejected"
            return {"status": "error", "error": str(e)}

    def _execute_confirmed(self, name: str, arguments: dict[str, Any]) -> Any:
        skill_name, action_name = self._name_map[name]
        # Resolve llm_spec from wiki_service
        llm_spec = None
        if self.wiki_service and hasattr(self.wiki_service, "get_llm_spec"):
            try:
                llm_spec = self.wiki_service.get_llm_spec()
            except Exception:
                pass
        config: dict[str, Any] = {"wiki_id": self.wiki_id} if self.wiki_id else {}
        if self.subagent_manager is not None:
            config["subagent_manager"] = self.subagent_manager
        if self.child_tool_registry is not None:
            config["child_tool_registry"] = self.child_tool_registry
        ctx = SkillContext(
            wiki=self.wiki,
            db=self.db,
            llm_spec=llm_spec,
            config=config,
            session_id=self.session_id,
        )
        _, action = self.skill_service.registry.find_action(skill_name, action_name)
        result = action.handler(arguments, ctx)
        if inspect.isawaitable(result):
            raise RuntimeError("Async skill confirmation requires async confirmation support")
        if isinstance(result, SkillResult):
            return result.to_dict()
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    def reject_execution(self, confirmation_id: str) -> dict[str, Any]:
        confirmation = self._pending_confirmations.pop(confirmation_id, None)
        if confirmation is None:
            return {"status": "error", "error": f"Unknown confirmation ID: {confirmation_id}"}
        confirmation["status"] = "rejected"
        return {"status": "rejected", "confirmation_id": confirmation_id}

    def confirm_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [self.confirm_execution(cid) for cid in confirmation_ids]

    def reject_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [self.reject_execution(cid) for cid in confirmation_ids]

    def get_pending_confirmations(self) -> list[dict[str, Any]]:
        return [
            c for c in self._pending_confirmations.values()
            if c.get("status") == "pending"
        ]

    def get_pending_by_group(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for confirmation in self.get_pending_confirmations():
            grouped.setdefault(confirmation.get("group", "skill_actions"), []).append(confirmation)
        return grouped


class CompositeToolRegistry:
    def __init__(self, *registries: Any):
        self.registries = [r for r in registries if r is not None]
        self._tools: dict[str, dict[str, Any]] = {}
        self._owners: dict[str, Any] = {}
        for registry in self.registries:
            for tool in registry.list_tools():
                name = tool["name"]
                if name in self._owners:
                    raise ValueError(f"Duplicate tool name: {name}")
                self._owners[name] = registry
                self._tools[name] = registry.get_tool(name) or tool

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for registry in self.registries:
            tools.extend(registry.list_tools())
        return tools

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self._tools.get(name)

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        owner = self._owners.get(name)
        if owner is None:
            available = ", ".join(sorted(self._owners.keys()))
            raise ValueError(f"Unknown tool: {name!r}. Available tools: [{available}]")
        return await owner.execute(name, arguments)

    @staticmethod
    def _is_unknown_confirmation(result: Any) -> bool:
        from llmwikify.apps.chat.agent.confirmation_manager import (
            ConfirmationManager as _CM,
        )
        return _CM.is_unknown_confirmation(result)

    def confirm_execution(self, confirmation_id: str, arguments: dict | None = None) -> Any:
        for registry in self.registries:
            result = registry.confirm_execution(confirmation_id, arguments)
            if not self._is_unknown_confirmation(result):
                return result
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    def reject_execution(self, confirmation_id: str) -> dict[str, Any]:
        for registry in self.registries:
            result = registry.reject_execution(confirmation_id)
            if not self._is_unknown_confirmation(result):
                return result
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    def confirm_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [self.confirm_execution(cid) for cid in confirmation_ids]

    def reject_batch(self, confirmation_ids: list[str]) -> list[dict[str, Any]]:
        return [self.reject_execution(cid) for cid in confirmation_ids]

    def get_pending_confirmations(self) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        for registry in self.registries:
            pending.extend(registry.get_pending_confirmations())
        return pending

    def get_pending_by_group(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for registry in self.registries:
            for group, items in registry.get_pending_by_group().items():
                grouped.setdefault(group, []).extend(items)
        return grouped
