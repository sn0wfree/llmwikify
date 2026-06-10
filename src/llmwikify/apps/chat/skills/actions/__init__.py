"""apps/chat/skills/actions/ — Phase 5: 26 base actions.

Per ``v0.32-skill-restructure.md`` §3.1 + ``v0.39-web-search-skill.md``,
the v0.32.0 base actions are 26 in total:

  14 base actions (#1-#14)
    1.  search_skill
    2.  extract_skill
    3.  read_skill
    4.  write_skill
    5.  lint_skill
    6.  plan_skill
    7.  analyze_skill
    8.  summarize_skill
    9.  score_skill
    10. revise_skill
    11. filter_skill
    12. graph_skill
    13. reason_skill
    14. observe_skill

  8 detect actions (#15-#22)
    15. detect_knowledge_gaps_skill
    16. detect_data_gaps_skill
    17. detect_outdated_pages_skill
    18. detect_dated_claims_skill
    19. detect_query_page_overlap_skill
    20. detect_missing_cross_refs_skill
    21. detect_potential_contradictions_skill
    22. detect_redundancy_skill

  1 clarify action (#23)
    23. clarify_skill

  3 web search actions (#24-#26, v0.39)
    24. web_search_skill.search_web
    25. web_search_skill.search_youtube
    26. web_search_skill.search_news

This ``__init__.py``:
  1. Imports all 26 Skill instances
  2. Exposes ``ALL_ACTIONS`` (the list of 26 Skill objects)
  3. Exposes ``register_all_actions(registry)`` for the
     default registration at app startup
  4. Exposes ``unregister_all_actions(registry)`` for tests
     that need isolation

Why a single import point
-------------------------

The SkillRegistry needs a way to discover all 26 actions
without each application site remembering to import them.
The Phase 6 (research_skill) and Phase 7 (harness eval
classes) work will rely on these 26 actions being
registered by default when the framework boots.

The list is also a **contract**: the framework ships exactly
26 actions; any deviation (e.g. 27th action) requires a
design update, not a silent addition.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.actions.analyze_action import analyze_skill
from llmwikify.apps.chat.skills.actions.clarify_action import clarify_skill
from llmwikify.apps.chat.skills.actions.detect import (
    ALL_DETECT_SKILLS,
)
from llmwikify.apps.chat.skills.actions.extract_action import extract_skill
from llmwikify.apps.chat.skills.actions.filter_action import filter_skill
from llmwikify.apps.chat.skills.actions.graph_action import graph_skill
from llmwikify.apps.chat.skills.actions.lint_action import lint_skill
from llmwikify.apps.chat.skills.actions.observe_action import observe_skill
from llmwikify.apps.chat.skills.actions.plan_action import plan_skill
from llmwikify.apps.chat.skills.actions.read_action import read_skill
from llmwikify.apps.chat.skills.actions.reason_action import reason_skill
from llmwikify.apps.chat.skills.actions.revise_action import revise_skill
from llmwikify.apps.chat.skills.actions.score_action import score_skill
from llmwikify.apps.chat.skills.actions.search_action import search_skill
from llmwikify.apps.chat.skills.actions.summarize_action import summarize_skill
from llmwikify.apps.chat.skills.actions.web_search_action import web_search_skill
from llmwikify.apps.chat.skills.actions.write_action import write_skill
from llmwikify.apps.chat.skills.registry import SkillRegistry

# 14 base actions
_BASE_ACTIONS = [
    search_skill,
    extract_skill,
    read_skill,
    write_skill,
    lint_skill,
    plan_skill,
    analyze_skill,
    summarize_skill,
    score_skill,
    revise_skill,
    filter_skill,
    graph_skill,
    reason_skill,
    observe_skill,
]

# 1 clarify action
_CLARIFY_ACTIONS = [clarify_skill]

# 3 web search actions (v0.39)
_WEB_SEARCH_ACTIONS = [web_search_skill]

ALL_ACTIONS = (
    _BASE_ACTIONS + _CLARIFY_ACTIONS + ALL_DETECT_SKILLS + _WEB_SEARCH_ACTIONS
)

assert len(ALL_ACTIONS) == 26, (
    f"Phase 5 contract violation: expected exactly 26 base "
    f"actions, got {len(ALL_ACTIONS)}. Update the inventory."
)


def register_all_actions(registry: SkillRegistry) -> int:
    """Register all 26 base actions into ``registry``.

    Returns the count registered (26). Safe to call on a
    registry that already has some of these — the
    registry's ``register(replace=True)`` default will
    overwrite, and the Skill instances' ``setup()`` will
    run again (idempotent for these thin wrappers).
    """
    for skill in ALL_ACTIONS:
        registry.register(skill)
    return len(ALL_ACTIONS)


def unregister_all_actions(registry: SkillRegistry) -> int:
    """Unregister all 26 base actions. Returns the count removed.

    Used by tests that need registry isolation.
    """
    count = 0
    for skill in ALL_ACTIONS:
        if registry.has(skill.name):
            registry.unregister(skill.name)
            count += 1
    return count


__all__ = [
    "ALL_ACTIONS",
    "register_all_actions",
    "unregister_all_actions",
    # Skill instances (re-exported for tests / direct access)
    "search_skill",
    "extract_skill",
    "read_skill",
    "write_skill",
    "lint_skill",
    "plan_skill",
    "analyze_skill",
    "summarize_skill",
    "score_skill",
    "revise_skill",
    "filter_skill",
    "graph_skill",
    "reason_skill",
    "observe_skill",
    "clarify_skill",
    "web_search_skill",
    "ALL_DETECT_SKILLS",
]
