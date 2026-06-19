"""SkillService — facade over the skill framework (v0.33.0).

Per v0.33-service-refactor.md, this is one of the 5+1
services. It exposes the existing skill framework
(``apps/chat/skills/``) as a single injection point for
the AgentService composition root.

Responsibilities:
  - Register all built-in skills (23 base actions + 4 CRUD
    + 2 pipelines + 1 aggregator)
  - Provide a single ``execute(skill_name, action, args, ctx)``
    interface
  - Populate ``SkillContext.config`` so CRUD skills work
    in production
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SkillService:
    """Facade over apps/chat/skills/ (Registry + Runtime)."""

    def __init__(self, registry: Any = None, runtime: Any = None,
                 memory_manager: Any = None, wiki_service: Any = None):
        self.registry = registry
        self.runtime = runtime
        self.memory_manager = memory_manager
        self.wiki_service = wiki_service
        self._initialized = False

    def initialize(self) -> None:
        """Initialize registry + runtime if not provided.

        Idempotent: safe to call multiple times.
        """
        if self._initialized:
            return
        if self.registry is None:
            from llmwikify.apps.chat.skills.registry import (
                default_registry,
            )
            self.registry = default_registry()
        if self.runtime is None:
            from llmwikify.apps.chat.skills.runtime import SkillRuntime
            self.runtime = SkillRuntime(self.registry)
        self._initialized = True

    def ensure_initialized(self) -> None:
        """Public alias for initialize()."""
        self.initialize()

    def register_all(self) -> None:
        """Register all built-in skills.

        This includes:
        - 23 base actions (Phase 5)
        - 4 CRUD skills (Phase 12b)
        - 2 pipelines (Phase 12a)
        - 1 aggregator (Phase 12c)
        - research_skill (Phase 6)
        """
        self.initialize()
        # 23 base actions
        try:
            from llmwikify.apps.chat.skills.actions import (
                register_all_actions,
            )
            register_all_actions(self.registry)
        except ImportError:
            logger.debug("Base actions not available")
        # 4 CRUD skills + Phase 8 goal skill
        try:
            from llmwikify.apps.chat.skills.crud import (
                dream_skill,
                goal_skill,
                memory_skill,
                notify_skill,
                scheduler_skill,
            )
            self.registry.register(memory_skill)
            self.registry.register(notify_skill)
            self.registry.register(scheduler_skill)
            self.registry.register(dream_skill)
            self.registry.register(goal_skill)
        except ImportError:
            logger.debug("CRUD skills not available")
        # 3 pipelines
        try:
            from llmwikify.apps.chat.skills.pipelines import (
                gather_skill,
                ingest_skill,
                report_skill,
            )
            self.registry.register(gather_skill)
            self.registry.register(ingest_skill)
            self.registry.register(report_skill)
        except ImportError:
            logger.debug("Pipeline skills not available")
        # research_skill (composite of pipelines + actions)
        try:
            from llmwikify.apps.chat.skills.research_skill import (
                research_skill,
            )
            self.registry.register(research_skill)
        except ImportError:
            logger.debug("research_skill not available")
        # wiki_query_skill (28-action aggregator)
        try:
            from llmwikify.apps.chat.skills.wiki_query_skill import (
                wiki_query_skill,
            )
            self.registry.register(wiki_query_skill)
        except ImportError:
            logger.debug("wiki_query_skill not available")
        # dynamic_workflow skill (workflow runner)
        try:
            from llmwikify.apps.chat.skills.workflows.skill import (
                DynamicWorkflowSkill,
            )
            self.registry.register(DynamicWorkflowSkill())
        except ImportError:
            logger.debug("dynamic_workflow skill not available")
        # autoresearch_compound skill (proposal-only AutoResearch workflow)
        try:
            from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
                autoresearch_compound_skill,
            )
            self.registry.register(autoresearch_compound_skill)
        except ImportError:
            logger.debug("autoresearch_compound skill not available")
        # plugin skills (~/.llmwikify/skills/)
        try:
            from llmwikify.apps.chat.skills.plugin_loader import load_plugins
            load_plugins(self.registry)
        except Exception:
            logger.debug("plugin loader failed")

    async def execute(
        self,
        skill_name: str,
        action: str,
        args: dict,
        ctx: Any,
    ) -> Any:
        """Execute a skill action via the runtime.

        Args:
            skill_name: Name of the skill (e.g., "search", "memory")
            action: Action within the skill (e.g., "search_pages")
            args: Arguments dict (validated against JSON schema)
            ctx: SkillContext (db, config, etc.)

        Returns:
            SkillResult
        """
        self.initialize()
        # Auto-inject managers into config for CRUD skills
        if ctx.config is not None:
            if self.memory_manager:
                ctx.config.setdefault("memory_manager", self.memory_manager)
            if self.wiki_service:
                wiki_id = ctx.config.get("wiki_id")
                try:
                    ctx.config.setdefault(
                        "dream_editor",
                        self.wiki_service.get_dream_editor(wiki_id),
                    )
                except (ValueError, KeyError):
                    pass
                try:
                    ctx.config.setdefault(
                        "notification_manager",
                        self.wiki_service.get_notification_manager(wiki_id),
                    )
                except (ValueError, KeyError):
                    pass
                try:
                    ctx.config.setdefault(
                        "scheduler",
                        self.wiki_service.get_scheduler(wiki_id),
                    )
                except (ValueError, KeyError):
                    pass
        return await self.runtime.execute(skill_name, action, args, ctx)

    def list_skills(self) -> list[dict]:
        """List all registered skills."""
        self.initialize()
        manifests = self.registry.all_manifests()
        return [m.to_dict() for m in manifests]

    def get_skill(self, name: str) -> Any:
        """Get a skill by name."""
        self.initialize()
        return self.registry.get(name)

    def reset(self) -> None:
        """Reset the registry (for tests)."""
        self._initialized = False
        self.registry = None
        self.runtime = None


__all__ = ["SkillService"]
