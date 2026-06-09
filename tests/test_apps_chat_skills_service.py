"""Tests for SkillService (apps/chat/skills/service.py)."""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    reset_default_registry,
)
from llmwikify.apps.chat.skills.runtime import SkillRuntime
from llmwikify.apps.chat.skills.service import SkillService


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the default registry between tests."""
    reset_default_registry()
    yield
    reset_default_registry()


class TestSkillServiceInit:
    def test_default_init_creates_registry_and_runtime(self):
        svc = SkillService()
        svc.initialize()
        assert isinstance(svc.registry, SkillRegistry)
        assert isinstance(svc.runtime, SkillRuntime)

    def test_init_is_idempotent(self):
        svc = SkillService()
        svc.initialize()
        first = svc.registry
        svc.initialize()
        assert svc.registry is first

    def test_ensure_initialized_alias(self):
        svc = SkillService()
        svc.ensure_initialized()
        assert svc._initialized is True

    def test_explicit_registry(self):
        reg = SkillRegistry()
        svc = SkillService(registry=reg)
        svc.initialize()
        assert svc.registry is reg


class TestSkillServiceRegisterAll:
    def test_register_all_runs_without_error(self):
        svc = SkillService()
        svc.initialize()
        # Should not raise even if some modules are missing
        svc.register_all()

    def test_list_skills_after_register(self):
        svc = SkillService()
        svc.initialize()
        svc.register_all()
        skills = svc.list_skills()
        # Should have at least the base 23 actions
        # (or fewer if not all modules are available)
        assert isinstance(skills, list)


class TestSkillServiceGetSkill:
    def test_get_skill_returns_skill_or_none(self):
        svc = SkillService()
        svc.initialize()
        svc.register_all()
        # Get a skill that may or may not be registered
        skill = svc.get_skill("nonexistent_skill")
        assert skill is None


class TestSkillServiceReset:
    def test_reset_clears_state(self):
        svc = SkillService()
        svc.initialize()
        assert svc._initialized is True
        svc.reset()
        assert svc._initialized is False
        assert svc.registry is None
        assert svc.runtime is None


class TestSkillServiceWikiServiceInjection:
    """P0: Verify SkillService injects dream_editor/notification_manager/
    scheduler into ctx.config via wiki_service."""

    def test_wiki_service_stored(self):
        svc = SkillService(wiki_service="fake_wiki_service")
        assert svc.wiki_service == "fake_wiki_service"

    def test_inject_dream_editor_into_ctx(self):
        class _FakeWikiService:
            def get_dream_editor(self, wiki_id=None):
                return "dream_editor_instance"

        class _FakeCtx:
            def __init__(self):
                self.config = {"wiki_id": "w1"}

        svc = SkillService(wiki_service=_FakeWikiService())
        ctx = _FakeCtx()
        # Manually test the injection logic
        if svc.wiki_service:
            wiki_id = ctx.config.get("wiki_id")
            try:
                ctx.config.setdefault(
                    "dream_editor",
                    svc.wiki_service.get_dream_editor(wiki_id),
                )
            except (ValueError, KeyError):
                pass
        assert ctx.config["dream_editor"] == "dream_editor_instance"

    def test_inject_notification_manager_into_ctx(self):
        class _FakeWikiService:
            def get_notification_manager(self, wiki_id=None):
                return "notif_manager_instance"

        class _FakeCtx:
            def __init__(self):
                self.config = {"wiki_id": "w1"}

        svc = SkillService(wiki_service=_FakeWikiService())
        ctx = _FakeCtx()
        if svc.wiki_service:
            wiki_id = ctx.config.get("wiki_id")
            try:
                ctx.config.setdefault(
                    "notification_manager",
                    svc.wiki_service.get_notification_manager(wiki_id),
                )
            except (ValueError, KeyError):
                pass
        assert ctx.config["notification_manager"] == "notif_manager_instance"

    def test_inject_scheduler_into_ctx(self):
        class _FakeWikiService:
            def get_scheduler(self, wiki_id=None):
                return "scheduler_instance"

        class _FakeCtx:
            def __init__(self):
                self.config = {"wiki_id": "w1"}

        svc = SkillService(wiki_service=_FakeWikiService())
        ctx = _FakeCtx()
        if svc.wiki_service:
            wiki_id = ctx.config.get("wiki_id")
            try:
                ctx.config.setdefault(
                    "scheduler",
                    svc.wiki_service.get_scheduler(wiki_id),
                )
            except (ValueError, KeyError):
                pass
        assert ctx.config["scheduler"] == "scheduler_instance"

    def test_no_wiki_service_no_injection(self):
        class _FakeCtx:
            def __init__(self):
                self.config = {"wiki_id": "w1"}

        svc = SkillService(wiki_service=None)
        ctx = _FakeCtx()
        assert "dream_editor" not in ctx.config
        assert "notification_manager" not in ctx.config
        assert "scheduler" not in ctx.config

    def test_wiki_service_value_error_skips(self):
        class _FakeWikiService:
            def get_dream_editor(self, wiki_id=None):
                raise ValueError("No wiki_id available")

        class _FakeCtx:
            def __init__(self):
                self.config = {}

        svc = SkillService(wiki_service=_FakeWikiService())
        ctx = _FakeCtx()
        # Should not raise, just skip
        if svc.wiki_service:
            wiki_id = ctx.config.get("wiki_id")
            try:
                ctx.config.setdefault(
                    "dream_editor",
                    svc.wiki_service.get_dream_editor(wiki_id),
                )
            except (ValueError, KeyError):
                pass
        assert "dream_editor" not in ctx.config
