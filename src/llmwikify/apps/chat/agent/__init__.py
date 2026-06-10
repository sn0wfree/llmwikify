"""apps/chat/agent/ — chat-level agent framework (Phase 8 of v0.32).

This subpackage is the new home for cross-skill agent glue code
that lives "above" the skills/ framework:

  - ``react_engine.py`` — unified ``ReActEngine`` (Reason → Act →
    Observe loop with 9 configurable hooks). Drives
    ``research_skill`` and any future ReAct-style skill.
    ``react_loop.py`` is a backward-compat re-export wrapper.

What does NOT live here
-----------------------

  - Skill definitions: ``apps/chat/skills/``
  - LLM provider wiring: ``apps/chat/providers/``
  - Tool registration: ``apps/agent/tools/`` (legacy)

Per the 4-layer refactor, ``apps/chat/agent/`` is L3; it may
import from ``apps/chat/skills/``, ``apps/chat/providers/``,
and ``apps/research/`` (chat reuses research per the
``chat-uses-research-and-agent`` contract).
"""
