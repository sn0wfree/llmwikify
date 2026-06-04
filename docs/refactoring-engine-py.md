# engine.py Refactoring Design

> **Status**: Design document (pre-implementation)
> **Created**: 2026-06-04
> **Author**: opencode + ll
> **Target file**: `src/llmwikify/autoresearch/engine.py` (1,492 LOC)
> **Goal**: Reduce by ~40% while keeping public API and 1,433 tests unchanged.

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
  - `docs/plans/ashare-strategy-building.md`
