"""llmwikify v0.50 Legacy ReAct Engine Archive

This directory contains the v1 ReAct engine stack (chat_react / react_engine /
react_loop / runner), **archived on 2026-06-18** as part of the Plan B
runner_v2 migration (B-5 cleanup substep).

## Why archived

In v0.50 (Plan B), the v1 ReAct loop stack was replaced by ``runner_v2.py``
(``ChatRunnerV2``), a clean 5-step state machine with 13/13 hook points
and 617 unit tests. The old stack has 3 layers of complexity:

- ``chat_react.py`` (723 LOC) — ``ChatReActBridge`` wires 5-method chat_service interface
- ``react_engine.py`` (687 LOC) — ``ReActEngine`` Reason → Act → Observe loop with 9 hooks
- ``react_loop.py`` (51 LOC) — backward-compat re-export wrapper
- ``runner.py`` (136 LOC) — Plan A Step 2 temporary facade (now superseded by ``runner_v2.py``)

Production never instantiates these. All chat paths go through
``ChatRunnerV2`` via ``AgentOrchestrator._chat_via_runner_v2`` (default since
B-5). The files here are kept for:

1. ``research_skill.py`` (auto-research /study) still imports ``ReactConfig``
   and ``ReactLoop`` for its multi-step research loop. Migrating it to v2
   is deferred to a future Plan B extension (out of B-5 scope).
2. Historical reference: comparison of v1 vs v2 design (file size,
   hooks, persistence integration, test coverage).

## Migration date

2026-06-18 (Plan B B-5 substep)
"""
