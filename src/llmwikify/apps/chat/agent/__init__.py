"""apps/chat/agent/ — chat-level agent framework (Phase 8 of v0.32).

This subpackage is the new home for cross-skill agent glue code
that lives "above" the skills/ framework:

  - ``runner_v2.py`` — :class:`ChatRunnerV2` (Plan B), the 5-step
    state machine (PRECHECK / REASON / ACT / OBSERVE / COMPLETE)
    with 13/13 ``AgentHook`` integration points and microcompact
    default-on. Replaces the legacy v1 ReAct engine stack.

  - ``orchestrator.py`` — :class:`ChatOrchestrator` (the main chat
    entry point), delegates the loop to ``ChatRunnerV2`` and
    handles session, abort, and SSE concerns.

  - ``spec.py`` — :class:`ChatRunSpec` / :class:`ChatRunResult`
    dataclasses that decouple spec from runner implementation.

  - ``microcompact.py`` — compact tool result to a marker for the
    next LLM turn (saves ~99% tokens on large read_file results).

  - ``text_mode_tool.py`` — Perl-style ``[TOOL_CALL]`` parser for
    non-tool-aware LLMs.

What does NOT live here
-----------------------

  - Skill definitions: ``apps/chat/skills/``
  - LLM provider wiring: ``apps/chat/providers/``
  - Tool registration: ``apps/agent/tools/`` (legacy)
  - The legacy v1 ReAct engine stack (``chat_react`` /
    ``react_engine`` / ``react_loop``) — moved to
    ``src/llmwikify/archive/llmwikify_v0_50_legacy/chat_legacy/``
    on 2026-06-18 (Plan B B-5 cleanup).

Per the 4-layer refactor, ``apps/chat/agent/`` is L3; it may
import from ``apps/chat/skills/``, ``apps/chat/providers/``,
and ``apps/research/`` (chat reuses research per the
``chat-uses-research-and-agent`` contract).
"""
