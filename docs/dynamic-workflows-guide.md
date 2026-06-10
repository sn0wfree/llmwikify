# Dynamic Workflows — Usage & Design Guide

> **Audience**: llmwikify operators (LLM-facing usage) and developers (extending or authoring workflows).
> **Status**: v1 ships with 1 built-in workflow (`llmwikify-research`), 4 actor prompts, and a full runtime. 40 tests pass; 0 regressions in the 2,405-test project suite.
> **Reading time**: 5 minutes for the main path. Drill into the linked docs as needed.

This guide is the **entry point** for the dynamic-workflow feature in llmwikify. For background, the underlying DSL specification, or implementation internals, see the linked documents at the end.

---

## 0. 30-second summary

Dynamic workflows let the llmwikify chat agent run **multi-agent research and processing tasks** by composing several independent subagents (planner, parallel researchers, adversarial verifier, synthesizer) under a top-level orchestrator. The orchestrator is a small Python runtime; the workflow topology is described in **YAML**; the LLM picks a built-in workflow by name and fills the inputs. Subagents run in **separate Python processes** so context, crash, and concurrency risks are isolated from the chat session.

The key design property: **the LLM cannot write code**. It can only pick a built-in workflow and provide JSON inputs.

---

## 1. The 1-minute tour for an LLM operator

If you are using the llmwikify chat agent (via Claude Code, opencode, Codex, the MCP server, or the WebUI), the workflow looks like this:

```text
You:   "Research how llmwikify's ReAct engine handles subagent failure."
Claude: I'll use the dynamic_workflow skill.
Claude: → calls dynamic_workflow.run(
              name="llmwikify-research",
              inputs={"question": "how llmwikify's ReAct engine handles subagent failure"}
          )
Claude: → waits (this can take 30s to several minutes)
Claude: → returns a cited report and the path to the new wiki page.
```

The LLM does **not** need to know about phases, actors, fan-outs, or how the orchestrator works. It treats `dynamic_workflow` as a single tool. Behind the scenes:

- The orchestrator's **planner** subagent (Opus) reads the question and produces 3–5 research phases.
- The orchestrator **fans out** one **researcher** subagent (Sonnet) per phase, running in parallel under isolated git worktrees.
- An **adversarial verifier** subagent (Sonnet, tuned to be skeptical) reads every claim and grades each as `accept` / `downgrade` / `reject`.
- A **synthesizer** subagent (Opus) is the only writer; it reads the surviving claims and produces a cited report at `research/<slug>.md`.
- The intermediate state lives on disk in `~/.llmwikify/workflows/runs/{run_id}.json` so an interrupted run can be resumed.

To check on a long run or to resume, the LLM calls `dynamic_workflow.status(run_id=...)` or `dynamic_workflow.resume(run_id=...)`.

If the LLM is uncertain whether to use a workflow, the heuristic is simple: **use a workflow when the task needs multi-source research, cross-checking, or parallel investigators**. For a single-fact lookup, prefer `wiki_query.search` or the existing `research_skill`.

---

## 2. The 5-minute tour for a developer

If you are extending llmwikify — adding a new built-in workflow, writing a new actor prompt, or hooking the runtime into the existing chat engine — read this section.

### 2.1 Where the code lives

```
src/llmwikify/apps/chat/skills/workflows/
├── __init__.py                          # public surface re-exports
├── dag.py                               # YAML/JSON parser + spec dataclasses + validator
├── executor.py                          # DAG runner, $-ref resolver, fan-out, scheduler
├── subagent_runner.py                   # one mp.Process per subagent
├── subagent_worker.py                   # in-process: prompt build + LLM call + JSON parse
├── run_store.py                         # persistent run state in ~/.llmwikify/...
├── skill.py                             # the DynamicWorkflowSkill (4 actions)
└── builtins/
    ├── __init__.py                      # built-in registry (globs the dir)
    ├── llmwikify-research.yaml          # the reference workflow
    └── actor_prompts/
        ├── wikify-research-planner.md
        ├── wikify-phase-researcher.md
        ├── wikify-adversarial-verifier.md
        └── wikify-synthesizer.md
```

The runtime is **independent** of the existing `apps/chat/engine.py` and `apps/chat/agent/react_engine.py`. It does not touch the ReAct loop. It is invoked by the `DynamicWorkflowSkill`, which itself is one of the 31 skills the chat engine can dispatch to. The dynamic workflow sits **next to** the existing `research_skill.py`, not in front of it.

### 2.2 The end-to-end flow

```
[LLM] → [DynamicWorkflowSkill.run] → [WorkflowExecutor.run]
                                          │
                                          ├─ validate spec (1×, cached)
                                          ├─ build DAG (1×, cached)
                                          │
                                          ├─ loop:
                                          │   ├─ materialize_fanouts()   ← upstream just done
                                          │   ├─ ready = find_ready_phases()
                                          │   ├─ for phase in ready: pool.submit(phase)
                                          │   ├─ wait for any future to finish
                                          │   ├─ record result (complete / failed)
                                          │   └─ check budget + wallclock
                                          │
                                          └─ return WorkflowRunResult

[WorkflowExecutor._execute_phase] → [SubagentRunner.run_subagent]
                                          │
                                          └─ spawn mp.Process → child reads from pipe
                                                              │
                                                              ▼
                                                  [SubagentWorker.run_subagent]
                                                              │
                                                              ├─ resolve prompt_file
                                                              ├─ build system + user messages
                                                              ├─ AgentDriver.complete(...)
                                                              │   ├─ LlmClientDriver → real LLM
                                                              │   └─ MockDriver      → test stub
                                                              └─ parse JSON, send back on pipe
```

### 2.3 The DSL in 60 seconds

A workflow YAML has this shape:

```yaml
version: 1
workflow:
  name: my-workflow
  description: "..."
  inputs:
    type: object
    properties:
      question: {type: string}
    required: [question]
  actors:
    planner: {prompt_file: actor_prompts/planner.md, model: opus}
    worker:  {prompt_file: actor_prompts/worker.md,  model: sonnet}
  phases:
    - id: plan
      actor: planner
      inputs: {question: $inputs.question}
      outputs: plan
    - id: gather
      actor: worker
      needs: [plan]
      fan_out:
        from: $plan.items
        id_prefix: gather_
        actor: worker
        inputs: {item: $item}
    - id: write
      actor: worker
      needs: [gather]
      inputs: {results: $gather.results}
```

The full DSL — input schemas, actor fields, fan-out semantics, $-reference resolution, the `skip_if` mini-expression language, the budget/limits model, the error/retry policy, and the runtime hard limits — is documented in [`dynamic-workflow-dsl.md`](./dynamic-workflow-dsl.md). The reference implementation is `builtins/llmwikify-research.yaml`.

### 2.4 Adding a new built-in workflow

The built-in registry globs `builtins/*.yaml`, so adding a new workflow is a 3-step process:

1. **Write the YAML** at `apps/chat/skills/workflows/builtins/your-workflow.yaml`. Use the existing `llmwikify-research.yaml` as a template.
2. **Write the actor prompts** at `apps/chat/skills/workflows/builtins/actor_prompts/your-actor.md`. These are plain markdown with YAML frontmatter. The body is the system prompt that the LLM sees; the frontmatter declares the actor's model + tools + isolation + permission mode.
3. **Test it** with the `MockDriver`:

   ```python
   import os
   os.environ["LLMWIKIFY_SUBAGENT_DRIVER"] = "mock"

   from pathlib import Path
   from llmwikify.apps.chat.skills.workflows import (
       DynamicWorkflowSkill, WorkflowInputs,
   )

   skill = DynamicWorkflowSkill()
   ctx = ...  # construct a SkillContext
   result = skill.actions["run"].handler(
       {"name": "your-workflow", "inputs": {"question": "..."}},
       ctx,
   )
   assert result.status == "ok", result.to_dict()
   ```

   The skill auto-discovers your new YAML on the next call. No registration step is required.

### 2.5 Writing an actor prompt that produces reliable JSON

The runtime does **not** retry on bad JSON. A phase that returns prose instead of JSON fails the workflow. The actor prompts in `builtins/actor_prompts/` follow three rules to keep JSON reliable:

1. **State the schema explicitly.** Each prompt contains a fenced ```json schema block showing the exact shape.
2. **End with "Return ONLY a JSON object. No prose, no markdown fences, no commentary before or after."**
3. **Use `context: fork`-style isolation**: each actor's context is fresh. The actor does not need to know about the LLM, the chat history, or other actors.

The worker's `_try_parse_json` is forgiving (it tries exact → fenced → first-balanced-object), but you should not rely on that. A prompt that **always** produces clean JSON is far more reliable than one that produces JSON 90% of the time.

### 2.6 Hooking into the existing chat engine

The `DynamicWorkflowSkill` is a v0.32-style `Skill` and is registered the same way as any other skill. To make the LLM see it, add it to the skill registry at chat-engine startup:

```python
from llmwikify.apps.chat.skills.workflows import DynamicWorkflowSkill
from llmwikify.apps.chat.skills import default_registry

default_registry().register(DynamicWorkflowSkill())
```

The skill manifest exposes 4 actions to the LLM. The chat engine handles confirmation prompts for the write actions (`run`, `resume`) just like any other skill. For long-running workflows, you can wrap the `run` handler in a background task (mirroring what `apps/research/gatherer.py` does) and return early with the `run_id`, letting the LLM poll via `status`.

### 2.7 Testing

The 40 tests in `tests/test_apps_chat_skills_workflows_*.py` follow the project's conventions:

- No real LLM calls (the `MockDriver` returns deterministic JSON).
- No network I/O.
- `tmp_path` and `monkeypatch.setenv` for isolation.
- The full project test suite (2,405 tests) continues to pass.

To add tests for a new built-in, add cases to `test_apps_chat_skills_workflows_runtime.py`. The pattern is:

```python
def test_my_workflow_runs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLMWIKIFY_SUBAGENT_DRIVER", "mock")
    # Set up a fresh RunStore
    monkeypatch.setattr(
        "llmwikify.apps.chat.skills.workflows.run_store.RunStore.default",
        classmethod(lambda cls: RunStore(tmp_path / "runs")),
    )

    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        result = skill.actions["run"].handler(
            {"name": "your-workflow", "inputs": {"question": "..."}},
            ctx,
        )
        assert result.status == "ok"
    finally:
        skill.teardown()
```

---

## 3. Configuration knobs

| Knob | Where | Default | What it does |
|---|---|---|---|
| `LLMWIKIFY_SUBAGENT_DRIVER` | env | `llm` | `mock` for tests, `llm` for production (anything else falls back to `mock` with a warning) |
| `max_concurrent_agents` | `workflow.budget` | 8 | Per-run semaphore on subprocess spawns |
| `max_total_tokens` | `workflow.budget` | none | Soft post-hoc cap; on exceed → `halt` (or `continue` if specified) |
| `max_total_agents` | `workflow.limits` | 100 | Hard cap on total subagents in a single run |
| `max_wallclock_seconds` | `workflow.limits` | 14400 (4h) | Hard cap on total run time |
| `max_phase_timeout_seconds` | `workflow.limits` | 1800 (30m) | Hard cap on any single phase |
| `on_exceed` | `workflow.budget` | `halt` | `halt` stops the run with state preserved; `continue` marks the phase as failed and proceeds |
| `isolation` | `actor` | `none` | `worktree` runs the subagent in an isolated git worktree (planned, not yet enforced in v1) |
| `permission_mode` | `actor` | `default` | `acceptEdits` auto-approves file writes (used by the synthesizer); others reserved for future use |
| `skip_if` | `phase` | none | Whitelisted expression (`len($X) <op> N`); phase is skipped when true |

All of these are per-workflow in the YAML. The runtime does not have global overrides. The `LLMWIKIFY_SUBAGENT_DRIVER` env var is the only cross-cutting knob.

---

## 4. Operational recipes

### 4.1 Inspect a run that crashed

```bash
cat ~/.llmwikify/workflows/runs/wf_2026-06-10T14-30-22_abc123.json
```

You'll see:

```json
{
  "run_id": "wf_2026-06-10T14-30-22_abc123",
  "workflow_name": "llmwikify-research",
  "status": "halted",
  "phases": {
    "plan": {"status": "complete", "output": {...}},
    "gather_0": {"status": "complete", "output": {...}},
    "gather_1": {"status": "running"},   ← the one that crashed
    "verify": {"status": "pending"},
    "synthesize": {"status": "pending"}
  },
  "total_tokens_used": 42310,
  "total_agents_spawned": 3
}
```

### 4.2 Resume a run

From the chat, ask the LLM: "resume run wf_2026-06-10T14-30-22_abc123". It calls `dynamic_workflow.resume(run_id=...)`.

Programmatically:

```python
from llmwikify.apps.chat.skills.workflows import DynamicWorkflowSkill
skill = DynamicWorkflowSkill()
ctx = SkillContext()
result = skill.actions["resume"].handler(
    {"run_id": "wf_2026-06-10T14-30-22_abc123"}, ctx,
)
```

Completed phases are skipped; pending and failed phases are re-run. Cumulative token/agent counts on the result reflect all work (including the original run), so the delta tells you how much extra work the resume did.

### 4.3 Force a particular model on a subagent

Inside the workflow YAML, set `actor.model` per actor:

```yaml
actors:
  planner: {prompt_file: ..., model: opus}
  worker:  {prompt_file: ..., model: sonnet}
```

This bypasses whatever the parent session's model is. Use this to keep research cheap (Sonnet) while keeping the plan and synthesis high-quality (Opus).

### 4.4 Add token-budget hard caps (v1.2+)

Today, the `max_total_tokens` budget is a soft post-hoc check: the executor sums `result.tokens_used` returned by each subagent and halts on exceed. The subagent itself is not aware of the budget. A future version will add a shared atomic counter that each subprocess reads and increments before each LLM call, so the cap is enforced **before** the call. Tracked for v1.2.

### 4.5 See the LLM prompts the runtime builds

Set `LLMWIKIFY_SUBAGENT_DRIVER=mock` in development. The `MockDriver.calls` list (in `subagent_worker.py`) records every prompt the runtime builds. Use it to debug "the LLM is being asked the wrong question" cases without burning real tokens.

---

## 5. Failure modes and what to do

| Symptom | Likely cause | Fix |
|---|---|---|
| `subagent timed out after Ns` | The LLM is slow, or the network is down | Increase `max_phase_timeout_seconds` in the workflow YAML. If recurring, check your LLM provider's status. |
| `failed to parse subagent result: ...` | The child process crashed mid-run | Check the `error` field for the traceback tail. Almost always an unhandled exception in the actor's prompt path. |
| `unknown $-reference root: 'X'` | A `$ref` points to a phase output that has not been computed yet | Check the DAG. `$X.Y` is only valid after the phase with `outputs: X` completes. |
| `cycle detected in phase DAG: A -> B -> A` | Two phases need each other | The validator catches this at load time. Re-design the dependency. |
| `fan_out.from=$X resolved to T, not list` | The upstream phase returned a non-list | Inspect the upstream actor's prompt. It must return a JSON object with a list-typed field. |
| `subagent X raised: ...` | The subagent crashed (not the LLM, the Python code) | The exception is logged. If it's in your actor prompt file, fix the prompt. If it's in the runtime, file a bug. |
| `budget exceeded` (after a long run) | `max_total_tokens` was set too low | Either increase the budget or split the run into multiple workflows. |
| `wallclock exceeded` (rare) | A subagent hung | Check your LLM provider. If the issue persists, the subagent is in a tight retry loop — review the actor prompt. |

All of these are surfaced via the `status` action or in the `run_store` JSON. There is no silent failure mode that the runtime hides from you.

---

## 6. How the existing llmwikify chat engine uses (or doesn't use) this

The dynamic-workflow runtime is **independent** of the ReAct engine. Concretely:

- `apps/chat/agent/react_engine.py` is **not** aware of `dynamic_workflow`. It sees `DynamicWorkflowSkill` as one more skill it can dispatch to.
- `apps/chat/skills/research_skill.py` (the 7-step ReAct research skill) is **not** replaced. It still works. `llmwikify-research` is a **parallel option** for research tasks, not a replacement.
- `apps/research/engine.py` and `apps/research/gatherer.py` are **not** changed. They continue to use `asyncio.gather + Semaphore` for in-process parallelism.

To migrate a user from `research_skill` to `llmwikify-research`:
1. Add `DynamicWorkflowSkill` to the default registry (see §2.6).
2. Update the LLM-facing prompts to nudge toward `dynamic_workflow` for multi-source research.
3. Track metrics: which skill wins for which query shape.

The v2 research (`docs/dynamic-workflows-research.md` §9) has more on the tradeoffs.

---

## 7. What we deliberately did NOT build (v1 scope)

These are tracked for v1.1+ and are **not** v1 limitations to fix immediately:

- **Real worktree isolation** (the frontmatter is parsed; the subprocess doesn't create a worktree yet).
- **Live CLI** (`llmwikify workflow status <run_id>`). The `status` action via the skill works; a dedicated CLI is pending.
- **Hard pre-call token cap** (the current cap is post-hoc).
- **LLM-generated workflows** (v1 ships only hand-written built-ins; the LLM picks from them).
- **Tournament pattern** as a first-class DSL operator.
- **Cross-workflow composition** (a workflow calling another workflow).
- **Slack / webhook notifications** on phase_complete.

Each of these is a self-contained 1–3 day piece of work. The implementation note (`docs/dynamic-workflow-impl.md` §5) has more on the tradeoffs.

---

## 8. Where to read next

| If you want to… | Read |
|---|---|
| Understand the broader feature landscape (Claude Code, agent teams, the 7 workflow patterns) | [`dynamic-workflows-research.md`](./dynamic-workflows-research.md) — 654 lines, the survey |
| Write a new workflow YAML | [`dynamic-workflow-dsl.md`](./dynamic-workflow-dsl.md) — 343 lines, the DSL spec |
| Understand the runtime internals (DAG runner, subprocess wiring, fan-out materialization) | [`dynamic-workflow-impl.md`](./dynamic-workflow-impl.md) — 612 lines, the implementation note |
| Read the research that motivated the feature | `dynamic-workflows-research.md` §0–§6 (Anthropic's design philosophy) |
| See the runtime's hard limits and behavior in edge cases | `dynamic-workflow-impl.md` §5 (what we didn't build) and §8 (open questions) |

---

*Last updated 2026-06-10. v1 ships.*
