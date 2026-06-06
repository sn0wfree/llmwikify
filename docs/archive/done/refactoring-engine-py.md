# engine.py Refactoring Design

> **Status**: Active — Phases 1-4 complete; Phase 2 (actions.py) in progress
> **Created**: 2026-06-04
> **Author**: opencode + ll
> **Target file**: `src/llmwikify/autoresearch/engine.py` (1,492 → 750 LOC, -50%)
> **Goal**: Reduce by ~50% while keeping public API and 1,433 tests unchanged.

## 0. Progress Tracker (2026-06-04)

| Phase | Commits | Status | engine.py LOC |
|-------|---------|--------|---------------|
| **Phase 1: Quick Wins + helpers + state + dict dispatch** | `478f704` → `40486ba` → `7a63e39` → `caef9d8` → `de3ec77` | ✅ Done | 1,492 → 1,369 (-8.2%) |
| **Phase 2: actions.py extraction (Step 2)** | `5a` → `5b` → `5c` (this section) | 🟡 In progress | 1,369 → ~750 (-45%) |
| **Phase 3: subpackage split** (deferred) | — | ⚪ Future | ~750 → ~600 |

**Phase 2 is what this document is about now.** Phases 1-4 of the original
plan were completed in commits `478f704`-`de3ec77` (see `git log`).

---

---

## 1. Problem Statement

`engine.py` is the orchestration heart of the autoresearch pipeline, but it
has accumulated **seven distinct responsibilities** in 1,492 lines:

| # | Concern | Lines | % of file |
|---|---------|-------|-----------|
| 1 | ReAct loop control (run, _react_loop, _reason) | ~270 | 18% |
| 2 | State management (ResearchState, _observe, _load_resume_state) | ~235 | 16% |
| 3 | LLM interaction (prompts + JSON parsing) | ~200 | 13% |
| 4 | Action dispatch (8 × `_action_*` methods) | ~530 | 36% |
| 5 | Database persistence (try/except wrappers) | ~80 | 5% |
| 6 | SSE event emission | ~50 | 3% |
| 7 | Rule-based fallbacks | ~80 | 5% |

`_react_loop` has **cyclomatic complexity ≈ 21** (healthy: <10). The 8-arm
`if/elif` action dispatch (lines 325-355) is the single biggest contributor.

**No public API change. No test change. 1,433 tests stay green.**

---

## 2. Target Architecture: 3 Layers

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: Loop orchestration (engine.py core)       │
│    - run()                                          │
│    - _react_loop()   ← dictionary dispatch          │
│    - _reason() + _rule_based_reason()               │
│    - _check_control_signals()                       │
│    ~350 lines                                       │
└─────────────────────────────────────────────────────┘
                        ↓ uses
┌─────────────────────────────────────────────────────┐
│  Layer 2: Action implementations (actions.py)       │
│    - BaseAction protocol                            │
│    - 9 action classes (Clarify/Plan/Gather/         │
│      Analyze/Synthesize/Report/Review/Revise/Done)  │
│    ~600 lines                                       │
└─────────────────────────────────────────────────────┘
                        ↓ uses
┌─────────────────────────────────────────────────────┐
│  Layer 3: Cross-cutting helpers (engine_helpers.py) │
│    - chat_json()         ← LLM+JSON pattern (6×)    │
│    - _safe_persist_*()   ← DB write wrappers (8×)   │
│    - state.py            ← ResearchState + metrics  │
│    ~300 lines combined                              │
└─────────────────────────────────────────────────────┘
```

---

## 3. Concrete Example: `_action_gather` Before & After

### Before (engine.py:858-927, 70 lines)

```python
async def _action_gather(self, state):
    # 7 lines of preamble (REPEATED in 8 actions)
    if not self._validate_transition(state.phase, "gathering"):
        logger.warning("Invalid transition to gathering from %s", state.phase)
    metrics = self._start_action("gather")
    state.phase = "gathering"
    self.session_manager.update_status(
        state.session_id, "gathering", "gathering", None
    )
    yield self._step_event("gathering", "开始采集")

    # ~50 lines of real work
    sources = await self.gatherer.gather(state.sub_queries)
    ...

    # 4 lines of try/except DB persist (REPEATED in 6 actions)
    try:
        self.session_manager.update_six_step_fields(
            state.session_id, evidence_scores=...
        )
    except Exception as e:
        logger.warning("Failed to persist: %s", e)

    # 3 lines of metrics finish (REPEATED in 8 actions)
    self._finish_action(metrics)
```

### After (actions.py, ~45 lines)

```python
class GatherAction(BaseAction):
    name = "gather"
    phase = "gathering"
    step_message = "开始采集"

    async def run(self, state):
        metrics = self._begin(state)         # preamble: 7 → 1
        sources = await state._engine.gatherer.gather(state.sub_queries)
        state.sources = sources
        ...real work unchanged ~50 lines...
        self._safe_persist_six_step(state,   # persist: 4 → 1
            evidence_scores=...)
        self._finish(metrics)                # metrics: 3 → 1
```

**Result**: 70 → 45 lines (-36%). Boilerplate lives in `BaseAction`.

---

## 4. Main Loop After Refactor (`_react_loop` simplified)

```python
async def _react_loop(self, session_id, query, resume):
    state = ...
    self._actions = {                           # ← single source of truth
        "plan":       PlanAction(self),
        "gather":     GatherAction(self),
        "analyze":    AnalyzeAction(self),
        "synthesize": SynthesizeAction(self),
        "report":     ReportAction(self),
        "review":     ReviewAction(self),
        "revise":     ReviseAction(self),
        "done":       DoneAction(self),
    }

    while state.phase != "done":
        if self._check_paused(): break

        action_name = await self._reason(state)    # LLM or rule-based
        action = self._actions.get(action_name,
                                   DoneAction(self))  # unknown → done

        async for event in action.run(state):     # ← 1 line, no if/elif
            yield event

        if action_name == "done":
            break
        state.round += 1
        if state.round >= state.max_rounds:
            ...
```

| Metric | Before | After |
|--------|--------|-------|
| `_react_loop` lines | ~115 | ~30 |
| if/elif arms | 8 | 0 (dict lookup) |
| Cyclomatic complexity | 21 | ~8 |
| New action requires editing? | yes (4 places) | no (1 line in dict) |

---

## 5. Key Helper APIs

### `engine_helpers.py::chat_json`

```python
async def chat_json(
    llm, messages, *, max_tokens=2048, temperature=0.3, json_mode=True
) -> Any:
    """Async wrapper: LLM.chat() in a thread + safe_json_loads().

    Replaces the same 6-line pattern that was duplicated at:
      - engine.py:510 (_llm_reason)
      - engine.py:1306 (_plan_sub_queries)
      - engine.py:1382 (_plan_for_gaps)
      - report.py:200 (generate)
      - review.py:62 (review)
      - clarifier.py:48 (clarify)
    """
    def _sync():
        return llm.chat(messages, json_mode=json_mode,
                        max_tokens=max_tokens, temperature=temperature)
    raw = await asyncio.to_thread(_sync)
    return safe_json_loads(raw)
```

### `engine_helpers.py::_safe_persist_*`

```python
def _safe_persist_status(state, status, step=None, **kwargs) -> None:
    try:
        state._engine.session_manager.update_status(
            state.session_id, status, step, **kwargs
        )
    except Exception as e:
        logger.warning("Persist status %s failed: %s", status, e)

def _safe_persist_six_step(state, **fields) -> None:
    try:
        state._engine.session_manager.update_six_step_fields(
            state.session_id, **fields
        )
    except Exception as e:
        logger.warning("Persist six-step %s failed: %s", list(fields), e)
```

Replaces 8 try/except blocks scattered across engine.py.

---

## 6. `BaseAction` Protocol

```python
# actions.py
from typing import Protocol, AsyncIterator

class BaseAction(Protocol):
    name: str           # action string: "plan" | "gather" | ...
    phase: str          # state.phase value: "planning" | "gathering" | ...
    step_message: str   # default SSE step event message

    def __init__(self, engine: "ResearchEngine"): ...

    async def run(self, state: ResearchState) -> AsyncIterator[dict]:
        """Execute the action. Yield SSE events. Mutate state."""
        ...

    def _begin(self, state) -> ActionMetrics:
        """Validate transition + start metrics + update status
        + emit step event. Returns metrics for _finish()."""
        if not state._engine._validate_transition(state.phase, self.phase):
            logger.warning("Invalid transition to %s from %s",
                           self.phase, state.phase)
        metrics = state._engine._start_action(self.name)
        state.phase = self.phase
        state._engine.session_manager.update_status(
            state.session_id, self.phase, self.phase, None
        )
        # yield via _emit_step — note: yielding from _begin would
        # require it to be a generator; instead the caller yields
        # the step event explicitly (or we wrap run() in a generator).
        return metrics

    def _finish(self, metrics: ActionMetrics) -> None:
        state._engine._finish_action(metrics)
```

**Trade-off note**: `_begin` cannot yield directly without becoming a
generator. Two options:

- **Option A** (chosen): caller yields the step event explicitly:

  ```python
  async def run(self, state):
      metrics = self._begin(state)
      yield state._engine._step_event(self.phase, self.step_message)
      ...
      self._finish(metrics)
  ```

- **Option B**: _begin returns the step event dict instead of metrics,
  caller does `event = self._begin(state); yield event`.

Option A is more explicit and matches current behavior 1:1.

---

## 7. `state.py` Extraction

Move the following from `engine.py:35-150` to a new `state.py`:

```python
# state.py
from dataclasses import dataclass, field

VALID_TRANSITIONS: dict[str | None, list[str]] = {
    None:           ["clarifying"],
    "clarifying":   ["planning"],
    "planning":     ["gathering"],
    "gathering":    ["analyzing", "planning"],   # replan path
    "analyzing":    ["synthesizing"],
    "synthesizing": ["reporting", "planning"],   # gap-replan
    "reporting":    ["reviewing"],
    "reviewing":    ["revising", "done"],
    "revising":     ["reviewing"],
}

@dataclass
class ActionMetrics: ...

@dataclass
class SessionMetrics: ...

@dataclass
class ResearchState:
    # ... all existing fields ...
    _engine: Any = field(default=None, repr=False, compare=False)
    # weak ref to ResearchEngine — needed by action classes to
    # call session_manager.update_status() etc.
```

`__init__.py` re-exports:

```python
from .state import (
    ResearchState, ActionMetrics, SessionMetrics, VALID_TRANSITIONS,
)
from .engine import ResearchEngine
```

This preserves all existing imports.

---

## 8. Test Compatibility (Zero Changes)

```python
# Current imports that must keep working
from llmwikify.autoresearch import (
    ResearchEngine,           # from .engine
    ResearchState,            # from .state (re-exported)
    VALID_TRANSITIONS,        # from .state (re-exported)
    ActionMetrics,            # from .state (re-exported)
    SessionMetrics,           # from .state (re-exported)
)
from llmwikify.autoresearch.engine import ResearchEngine
```

All preserved by `__init__.py` re-exports. No test file edits required.

---

## 9. Migration Plan (5 Commits, Git First)

### Commit 1: Quick Wins (30 min) — *this PR or next*

7 dead-code / latent-bug cleanups, **0 behavior change**:

| # | File:Line | Change | LOC delta |
|---|-----------|--------|-----------|
| 1 | engine.py:28 | Delete unused `WebSearch` import | -1 |
| 2 | clarifier.py:35 | Delete wrong-key `self.max_tokens = ...` | -1 |
| 3 | config.py:95 + engine.py:21 | Delete `merge_research_config` alias; rename import | -1 |
| 4 | retry_managers.py | Delete 3 unused `*RetryManager` classes | -150 |
| 5 | engine.py | Replace 8 `_validate_transition` + warning calls with `_warn_invalid_transition()` | -16 |
| 6 | report.py:268 | Fix `asyncio.run()` in sync generator | -4 |
| 7 | session.py + 4 others | Move 8 in-function `import json` to module top | -8 |

**Verification**: 1,433 tests pass.

### Commit 2: engine_helpers.py (1 hr)

- New file: `engine_helpers.py` with `chat_json()` + 2× `_safe_persist_*`
- Replace 6 LLM+JSON sites (engine:3, report:1, review:1, clarifier:1)
- Replace 8 try/except persist sites (engine:6, others:2)

**Verification**: 1,433 tests pass.

### Commit 3: state.py extraction (30 min)

- New file: `state.py` with `ResearchState` + 3 metrics classes + `VALID_TRANSITIONS`
- `engine.py` imports from `state.py`
- `__init__.py` re-exports

**Verification**: 1,433 tests pass.

### Commit 4: actions.py + dictionary dispatch (1.5 hr)

- New file: `actions.py` with `BaseAction` + 9 action classes
- `engine.py` deletes 8 `_action_*` methods
- `_react_loop` switches to dictionary dispatch

**Verification**: 1,433 tests pass + 1 live session with SSE event inspection.

### Commit 5 (optional, deferred): subpackage split

Convert `engine.py` → `engine/` subpackage with 9 files. Higher risk;
defer until Commit 4 is stable for a release cycle.

---

## 10. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Dict dispatch breaks SSE event ordering | Very low | Medium | Keep yield chain identical; verify live |
| `ResearchState._engine` weak ref breaks serialization | Low | Medium | Use `field(default=None, repr=False, compare=False)` |
| Deleted RetryManager classes used externally | Very low | Low | `git grep "from.*retry_managers import.*\(Stage\|LLM\|DB\)RetryManager"` |
| `asyncio.run()` fix changes streaming behavior | Medium | Medium | Add full test for `report.generate_streaming` both sync and async |
| Test mocks private engine symbols | Very low | Medium | Confirmed via `grep` — none observed |

---

## 11. Final Target State

| File | Before | After | Δ |
|------|--------|-------|---|
| `engine.py` | 1,492 | **~900** | -40% |
| `actions.py` | 0 | ~600 | new |
| `engine_helpers.py` | 0 | ~150 | new |
| `state.py` | 0 | ~150 | new |
| `retry_managers.py` | ~290 | ~140 | -150 (dead code) |
| **Total** | 1,492 | ~1,940 | +30% but distributed |

**Total LOC goes up slightly** because new files add imports and class
definitions, but the **cognitive load** drops dramatically:

- `engine.py` fits in **2 screens** (was 8+)
- Each action class is **independently testable**
- Adding a new stage = **1 new class + 1 dict line**, no surgery on engine

---

## 12. Out of Scope

- Subpackage split (Commit 5) — defer
- State management decoupling (remove `_engine` ref) — bigger arch change
- Web UI impact — none
- Performance optimization — not the bottleneck

---

## 13. References

- Baseline: commit `31d7ce8` (post Commit C of LLM JSON fix)
- Test baseline: 1,433 passed, 2 pre-existing v019 failures unrelated
- WIP files (do not touch during this work):
  - `src/llmwikify/agent/backend/ppt/chat_engine.py`
  - `src/llmwikify/agent/backend/ppt/chat_routes.py`
  - `src/llmwikify/agent/tools.py`
  - `docs/designs/ashare-strategy-building.md`

---

# Appendix A: Phase 2 — actions.py Extraction (Step 2)

> **Added**: 2026-06-04
> **Replaces**: Section 9 "Commit 4: actions.py + dictionary dispatch"
> **Decision**: Use **free functions + ActionContext** instead of `BaseAction`
> classes (smaller change, less indirection, no MRO complexity).

## A.1 Why free functions, not classes

We considered two designs:

| Approach | Pros | Cons |
|----------|------|------|
| `BaseAction` class with 9 subclasses (originally planned) | OO, polymorphism | 9 class definitions, 1 base class, MRO complexity, _engine weak-ref plumbing, ~600 LOC of boilerplate |
| **Free functions + ActionContext** ✅ | Simpler, explicit deps, easier to test | 1 dataclass, 9 functions, ~650 LOC with less boilerplate |

The original `BaseAction` design in Section 6 above is **superseded**.
We use free functions; the `_begin/_finish` boilerplate lives in
`MetricsCollector.record()` (a context manager) — see Appendix A.5.

## A.2 Target Architecture (Post Phase 2)

```
┌─────────────────────────────────────────────────────┐
│  engine.py: pure orchestrator  (~750 LOC, was 1,369)│
│    - __init__ (assembles ActionContext)             │
│    - run() (public entry)                           │
│    - _react_loop() (ReAct cycle)                    │
│    - _reason / _llm_reason / _rule_based_reason      │
│    - _observe / _evaluate_gate / _synthesis_to_text │
│    - _check_timeout / _check_control_signals         │
│    - _load_resume_state                             │
│    - _resolve_model                                 │
│    - module constants                               │
└─────────────────────────────────────────────────────┘
                       ↓ uses
┌─────────────────────────────────────────────────────┐
│  actions.py: 9 free functions + 5 helpers (~650 LOC)│
│    - ActionContext (dataclass)                      │
│    - action_clarify / plan / gather / analyze /     │
│      synthesize / report / review / revise / done   │
│    - _step_event / _warn_invalid_transition /       │
│      _plan_sub_queries / _plan_for_gaps /           │
│      _build_six_step_context                        │
└─────────────────────────────────────────────────────┘
                       ↓ uses
┌─────────────────────────────────────────────────────┐
│  state.py: state + metrics (already exists)         │
│    - ResearchState                                  │
│    - MetricsCollector (NEW) with record() ctx mgr   │
│    - ActionMetrics (value type)                     │
│    - SessionMetrics = MetricsCollector (alias)      │
│    - VALID_TRANSITIONS                              │
└─────────────────────────────────────────────────────┘
```

## A.3 ActionContext Design

A single dataclass holds all deps that 9 actions need. Built once in
`ResearchEngine.__init__`, passed to each action via `functools.partial`.

```python
# actions.py
from dataclasses import dataclass
from collections.abc import AsyncIterator

@dataclass
class ActionContext:
    """All deps the 9 action functions need. Constructed once in
    ResearchEngine.__init__, captured by partial() at dispatch time."""
    wiki: Any
    db: AutoResearchDatabase
    session_manager: ResearchSessionManager
    clarifier: ResearchClarifier
    gatherer: SourceGatherer
    analyzer: SourceAnalyzer
    synthesizer: ResearchSynthesizer
    report: ReportGenerator
    reviewer: ResearchReviewer
    revisor: ResearchRevisor
    quality_gate: QualityGate
    config: dict[str, Any]
    metrics: MetricsCollector
    planning_llm: StreamableLLMClient
```

**14 fields**. Of these, 7 (clarifier/gatherer/analyzer/synthesizer/
report/reviewer/revisor) are used by **exactly one** action each. We
still pass them all through `ActionContext` for consistency — the cost
is 14 reference assignments in `__init__`, paid once.

## A.4 Action Function Signatures

```python
async def action_clarify(
    ctx: ActionContext, state: ResearchState,
) -> AsyncIterator[dict[str, Any]]: ...

async def action_plan(
    ctx: ActionContext, state: ResearchState,
) -> AsyncIterator[dict[str, Any]]: ...

# ... 7 more, all with the same signature
```

**All 9 actions share the same signature**: `(ctx, state) -> AsyncIterator[dict]`.
The dispatch table uses `functools.partial(actions.action_xxx, ctx)` to
pre-bind the `ctx` argument:

```python
# engine.py __init__
from functools import partial
from llmwikify.autoresearch import actions

self._action_dispatch: dict[str, Callable] = {
    "clarify":    partial(actions.action_clarify, ctx),
    "plan":       partial(actions.action_plan, ctx),
    "gather":     partial(actions.action_gather, ctx),
    "analyze":    partial(actions.action_analyze, ctx),
    "synthesize": partial(actions.action_synthesize, ctx),
    "report":     partial(actions.action_report, ctx),
    "review":     partial(actions.action_review, ctx),
    "revise":     partial(actions.action_revise, ctx),
    "done":       partial(actions.action_done, ctx),
}
```

Then in `_react_loop`:

```python
action_fn = self._action_dispatch.get(action)
if action_fn is None:
    logger.warning("Unknown action %s, defaulting to done", action)
    action_fn = self._action_dispatch["done"]
    async for event in action_fn(state):
        yield event
    break
async for event in action_fn(state):
    yield event
if action == "done":
    break
```

**Same dispatch pattern as Commit 4** (`de3ec77`), just with free
functions instead of bound methods.

## A.5 MetricsCollector + record() Context Manager

Originally planned as a separate "Step 1" (Metrics consolidation). We
fold it into Commit 5c because the context manager is most useful
**inside** the action functions in `actions.py`. Doing it earlier
would require re-touching the action code.

**state.py additions**:

```python
from contextlib import contextmanager
from collections.abc import Iterator
import logging

logger = logging.getLogger(__name__)

@contextmanager
def _record_action_impl(
    collector: "MetricsCollector", action: str,
) -> Iterator["ActionMetrics"]:
    """Context manager body: start/finish + append action metrics."""
    m = ActionMetrics(action=action, start_time=time.monotonic())
    try:
        yield m
    finally:
        m.finish()
        collector.actions.append(m)
        logger.debug("Action %s completed in %dms", m.action, m.duration_ms)


@dataclass
class MetricsCollector:
    """Session-level metrics: aggregates per-action metrics.
    
    Replaces the previous SessionMetrics + the engine's
    _start_action / _finish_action helpers.
    """
    session_id: str
    start_time: float = 0.0
    end_time: float = 0.0
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    actions: list[ActionMetrics] = field(default_factory=list)
    
    def start(self) -> None: ...
    def finish(self) -> None: ...
    def add_action(self, action: ActionMetrics) -> None: ...  # back-compat
    def summary(self) -> str: ...
    def record(self, action: str) -> Iterator[ActionMetrics]:
        return _record_action_impl(self, action)


# Back-compat alias
SessionMetrics = MetricsCollector
```

**Bonus bug fix**: the previous code called `self._start_action(...)`
then `self._finish_action(...)` with **no try/finally** around the body.
If the body raised, the action metric was created but never recorded.
The new `with ctx.metrics.record("plan"):` pattern automatically runs
the finally block on exception — fixing a latent bug for free.

## A.6 Helper Migration (moved from engine.py → actions.py)

| Helper | LOC | Used by | Migrate? |
|--------|-----|---------|----------|
| `_step_event` | 3 | 7 actions | ✅ |
| `_warn_invalid_transition` | 8 | 6 actions | ✅ |
| `_plan_sub_queries` | 63 | 1 action (plan) | ✅ |
| `_plan_for_gaps` | 67 | 1 action (plan) | ✅ |
| `_build_six_step_context` | 22 | 2 actions (report, review) | ✅ |
| `_synthesis_to_text` | 38 | 1 action (synthesize) **+ 1 non-action (`_evaluate_gate`)** | ❌ stays in engine.py |

**5 helpers migrate to `actions.py`**, 1 stays.

## A.7 Commit Plan (3 Commits)

### Commit 5a: actions.py skeleton + 3 actions

- **New file**: `actions.py` with:
  - `ActionContext` dataclass
  - 3 action functions: `action_clarify`, `action_plan`, `action_gather`
  - 4 helpers: `_step_event`, `_warn_invalid_transition`, `_plan_sub_queries`, `_plan_for_gaps`
- **engine.py unchanged** (9 `_action_*` methods still in place)
- **Test**: `pytest tests/test_autoresearch.py tests/test_research.py -q` → 202/202
- **Risk**: Very low. No production code path uses the new functions yet.

### Commit 5b: complete 6 actions

- **actions.py additions**:
  - 6 more action functions: `action_analyze`, `action_synthesize`, `action_report`, `action_review`, `action_revise`, `action_done`
  - 1 more helper: `_build_six_step_context`
- **engine.py unchanged**
- **Test**: 202/202
- **Risk**: Low. Still no engine.py changes.

### Commit 5c: switch dispatch + delete old methods + MetricsCollector

- **state.py additions**:
  - `MetricsCollector` class
  - `SessionMetrics = MetricsCollector` alias
  - `_record_action_impl` helper
  - `import logging; logger = ...`
- **`__init__.py` additions**:
  - Re-export `MetricsCollector`
- **engine.py changes**:
  - Construct `ActionContext` in `__init__` (uses existing fields)
  - Build `self._action_dispatch` with `functools.partial`
  - Update `_react_loop` dispatch to use `self._action_dispatch` (already done in Commit 4 — just change the dict construction site)
  - **Delete 9 `_action_*` methods** (~500 lines)
  - **Delete 5 helpers**: `_step_event`, `_warn_invalid_transition`, `_plan_sub_queries`, `_plan_for_gaps`, `_build_six_step_context` (~165 lines)
  - **Delete `_start_action` and `_finish_action` helpers** (~10 lines)
  - `self._metrics` now `MetricsCollector` (was `SessionMetrics`)
  - `self._metrics = MetricsCollector(session_id=...)` (init site)
- **actions.py changes**:
  - Each of 9 action bodies: replace `metrics = self._start_action("xxx")` / `self._finish_action(metrics)` with `with ctx.metrics.record("xxx"):`
- **Test**: 1,433/1,433 (or 1,431 with 2 pre-existing v019 failures)
- **Risk**: Medium. Largest single change, but staged by 5a/5b.

## A.8 Final Target State (Post Commit 5c)

| File | Before (post Phase 1) | After (post Phase 2) | Δ |
|------|----------------------|---------------------|---|
| `engine.py` | 1,369 | **~750** | **-619 (-45%)** |
| `actions.py` | 0 | **~650** | new |
| `state.py` | 154 | **~200** | +46 (MetricsCollector) |
| `__init__.py` | 49 | **~52** | +3 (export MetricsCollector) |
| **Total** | 1,572 | **~1,652** | +80 (+5%) |

**Total LOC +5%, cognitive load -45%** in `engine.py`.

## A.9 Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| SSE event order changes | M | Tests fail | `test_engine_runs_all_six_steps_to_done` is the key guard |
| `self.xxx` → `ctx.xxx` mechanical errors | M | Runtime AttributeError | Run tests after each action extracted |
| Async generator + `with MetricsCollector.record()` | L | State leak | Same pattern works as in current code; verified |
| `_plan_sub_queries` / `_plan_for_gaps` use LLM directly | M | LLM not available | `planning_llm` field on `ActionContext` |
| Public API breaks | VL | External callers | `_action_*` is private (`_`-prefixed); only `run()` is public |
| Helper migration misses a caller | L | NameError at runtime | `git grep` after each commit to verify zero `self._step_event` etc. |

## A.10 Verification Steps (after Commit 5c)

```bash
# 1. Per-target unit tests (~30s)
python3 -m pytest tests/test_autoresearch.py tests/test_research.py -q
# Expected: 202 passed

# 2. Full suite (~3 min)
python3 -m pytest tests/ -q --ignore=tests/test_relation_engine.py --ignore=tests/e2e/test_editor.py
# Expected: 1,433 passed, 2 pre-existing v019 failures (unrelated)

# 3. Live verification (user-initiated, requires manual server restart)
#    - Start server: llmwikify serve --web --port 8765 --host 0.0.0.0
#    - POST /api/autoresearch/sessions with test query
#    - Check ~/.llmwikify/agent/server.log for:
#        * 0 "Unknown action" warnings (dispatch works)
#        * 0 "LLM reasoning failed" warnings (json_mode fix holds)
#        * All expected SSE event types: step, clarification_complete, sub_query_created, source_added, analysis_complete, synthesis_complete, report_complete, review_complete, done
```

## A.11 References

- Phase 1 commits: `478f704` → `40486ba` → `7a63e39` → `caef9d8` → `de3ec77`
- Phase 2 commits: pending (this section)
- Test baseline: 1,433 passed
- WIP files (do not touch during Phase 2):
  - `src/llmwikify/agent/backend/ppt/chat_engine.py`
  - `src/llmwikify/agent/backend/ppt/chat_routes.py`
  - `src/llmwikify/agent/tools.py`
  - `docs/designs/ashare-strategy-building.md`
