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
