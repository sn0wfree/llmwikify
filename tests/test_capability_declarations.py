"""Contract tests for the explicit capability declarations.

Two declarations replaced hidden contracts:

* ``Rule.snapshot_mode`` — a lint rule says whether it reads its
  pages in its own way (``"custom"``) or uses the generic template
  (``"template"``). It used to be a reflection check
  (``type(self).run is not Rule.run``), so a rule author who overrode
  ``run()`` without knowing about it silently lost the page-snapshot
  optimisation — no error, no warning.

* ``Skill.exposed`` — a skill says whether the LLM may call it. The
  tool adapter used to carry its own hardcoded list, so a skill that
  was registered but never listed was silently uncallable.
"""

from __future__ import annotations

from typing import Any

import pytest

from llmwikify.apps.chat.skills.base import Skill
from llmwikify.apps.chat.skills.registry import SkillRegistry
from llmwikify.apps.chat.skills.service import SkillService
from llmwikify.kernel.wiki.lint import CrossPageRule, Rule
from llmwikify.kernel.wiki.lint.rules import RULES

# ══════════════════════════════════════════════════════════════════
# Lint rules — snapshot_mode
# ══════════════════════════════════════════════════════════════════


def _all_rules() -> list[Rule]:
    """Every registered lint rule."""
    return list(RULES)


def test_snapshot_mode_has_only_known_values() -> None:
    """A typo in the declaration must not silently disable the snapshot."""
    for rule in _all_rules():
        assert rule.snapshot_mode in ("template", "custom"), (
            f"{type(rule).__name__}.snapshot_mode is {rule.snapshot_mode!r}"
        )


def test_template_rules_do_not_override_the_page_iteration() -> None:
    """A ``template`` rule must not override what the template does.

    Overriding ``run()`` / ``_iter_pages()`` / ``_load_pages()`` while
    claiming ``template`` is exactly the bug the declaration was
    introduced to make visible.
    """
    for rule in _all_rules():
        if rule.snapshot_mode != "template":
            continue
        cls = type(rule)
        assert cls.run is Rule.run or cls.run is CrossPageRule.run, (
            f"{cls.__name__} declares snapshot_mode='template' but overrides run()"
        )
        assert cls._iter_pages is Rule._iter_pages, (
            f"{cls.__name__} declares snapshot_mode='template' but overrides _iter_pages()"
        )
        if isinstance(rule, CrossPageRule):
            assert cls._load_pages is CrossPageRule._load_pages, (
                f"{cls.__name__} declares snapshot_mode='template' but overrides _load_pages()"
            )


def test_custom_rules_own_run_with_snapshot() -> None:
    """A ``custom`` rule without its own snapshot path would lose it."""
    for rule in _all_rules():
        if rule.snapshot_mode != "custom":
            continue
        cls = type(rule)
        assert cls.run_with_snapshot is not Rule.run_with_snapshot, (
            f"{cls.__name__} declares snapshot_mode='custom' but does not "
            "implement run_with_snapshot()"
        )
        assert cls.run_with_snapshot is not CrossPageRule.run_with_snapshot, (
            f"{cls.__name__} declares snapshot_mode='custom' but does not "
            "implement run_with_snapshot()"
        )


def test_every_custom_rule_overrides_run() -> None:
    """``custom`` without a custom ``run()`` is a contradiction."""
    for rule in _all_rules():
        if rule.snapshot_mode != "custom":
            continue
        cls = type(rule)
        assert cls.run is not Rule.run and cls.run is not CrossPageRule.run, (
            f"{cls.__name__} declares snapshot_mode='custom' but uses the "
            "generic run()"
        )


def test_snapshot_mode_replaces_the_reflection() -> None:
    """The declaration decides, not the shape of the class.

    A rule that overrides ``run()`` *and* declares ``custom`` must go
    through its own path even when a snapshot is available.
    """
    custom = [r for r in _all_rules() if r.snapshot_mode == "custom"]
    template = [r for r in _all_rules() if r.snapshot_mode == "template"]
    assert custom, "no custom rules — the registry would be empty"
    assert template, "no template rules — the generic template would be dead code"


# ══════════════════════════════════════════════════════════════════
# Skills — exposed
# ══════════════════════════════════════════════════════════════════


def test_skill_exposed_defaults_to_false() -> None:
    """A skill is internal unless it opts in."""
    assert Skill.exposed is False


def test_registry_exposed_names_match_the_declarations() -> None:
    """``exposed_names`` is exactly the skills that opted in."""
    service = SkillService()
    service.register_all()
    registry = service.registry

    declared = {
        skill.name for skill in registry if getattr(skill, "exposed", False)
    }
    assert set(registry.exposed_names()) == declared
    assert declared, "no skill is exposed — the LLM would have no tools"


def test_adapter_asks_the_registry() -> None:
    """The adapter's default exposed set comes from the registry."""
    from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter

    service = SkillService()
    service.register_all()
    adapter = SkillToolAdapter(service)

    assert set(adapter.exposed_skills) == set(service.registry.exposed_names())


def test_adapter_exposes_nothing_extra() -> None:
    """Every tool belongs to a skill that opted in."""
    from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter

    service = SkillService()
    service.register_all()
    adapter = SkillToolAdapter(service)

    for tool_name, (skill_name, _action) in adapter._name_map.items():
        if skill_name == "__builtin__":
            continue
        assert skill_name in adapter.exposed_skills, (
            f"{tool_name} is a tool of the non-exposed skill {skill_name!r}"
        )


def test_explicit_exposed_skills_still_win() -> None:
    """A caller may narrow or widen the set explicitly."""
    from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter

    service = SkillService()
    service.register_all()
    adapter = SkillToolAdapter(service, exposed_skills=["web_search"])

    assert adapter.exposed_skills == {"web_search"}
    names = {t["name"] for t in adapter.list_tools()}
    assert all(n.startswith("web_search") or n == "get_skill_commands" for n in names)


def test_registry_without_exposed_names_is_tolerated() -> None:
    """A registry that predates the declaration must not crash the adapter."""
    from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter

    class OldRegistry:
        def all_actions(self) -> list:
            return []

    class OldService:
        registry = OldRegistry()

        def register_all(self) -> None:
            return None

    adapter = SkillToolAdapter(OldService())
    assert adapter.exposed_skills == set()


def test_registry_exposed_names_is_sorted() -> None:
    """Deterministic order — the tool surface must not depend on dict order."""
    registry = SkillRegistry()
    assert registry.exposed_names() == sorted(registry.exposed_names())


@pytest.mark.parametrize("name", ["web_search", "web_fetch", "dynamic_workflow"])
def test_the_public_skills_are_exposed(name: str) -> None:
    """The skills that used to be hardcoded stay exposed."""
    service = SkillService()
    service.register_all()
    assert name in service.registry.exposed_names()


def test_internal_skills_are_not_exposed() -> None:
    """The action-only skills stay internal."""
    service = SkillService()
    service.register_all()
    exposed = set(service.registry.exposed_names())
    for internal in ("read", "write", "lint", "wiki_query", "memory", "goal"):
        assert internal not in exposed, f"{internal} should not be exposed"
