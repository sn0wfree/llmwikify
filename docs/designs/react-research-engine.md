# ReAct Research Engine — Design Document

## Overview

Redesign the Quick Research pipeline from a **fixed 7-stage sequential flow** to an
**adaptive ReAct (Reason → Act → Observe → loop) agent** that dynamically decides
what to do next based on intermediate results.

## Problem Statement

Current pipeline (`engine.py`) runs stages in fixed order:

```
Planning → Gathering → Analyzing → Synthesizing → Report → Reviewing → Done
```

**Issues:**
1. **No adaptation** — if Planning produces poor sub-queries, the entire pipeline wastes effort
2. **No feedback loop** — if Analyzing reveals information gaps, no re-gathering happens
3. **Review is binary** — pass/fail with max 2 rounds, no partial re-collection
4. **No learning** — each stage runs independently, ignoring insights from prior stages
5. **Fixed budget** — all sub-queries searched upfront, no prioritization based on quality

## ReAct Pattern

```
┌─────────────────────────────────────────────────┐
│              ReAct Research Loop                 │
│                                                  │
│  Reason ──→ Act ──→ Observe ──→ Evaluate ──┐   │
│     ▲                                      │   │
│     └──────────────────────────────────────┘   │
│                                                  │
│  Exit when: quality达标 OR 预算耗尽 OR 轮次上限   │
└─────────────────────────────────────────────────┘
```

**Key difference:** The agent **decides** what to do next, rather than following a
predefined sequence.

## Architecture

### 1. Research State

A single `ResearchState` object tracks everything:

```python
@dataclass
class ResearchState:
    # Identity
    session_id: str
    query: str

    # Current state
    round: int                    # Current ReAct round (1-based)
    max_rounds: int               # Config max (default 5)
    phase: str                    # "planning" | "gathering" | "analyzing" | "synthesizing" | "reporting" | "reviewing" | "done"

    # Data
    sub_queries: list[dict]       # All sub-queries (original + replanned)
    sources: list[dict]           # All gathered sources
    synthesis: dict | None        # Latest synthesis result
    report_md: str | None         # Latest report markdown
    review: dict | None           # Latest review result

    # Quality tracking
    quality_score: int            # Latest review score (0-10)
    knowledge_gaps: list[str]     # Detected gaps from synthesis
    contradictions: list[str]     # Detected contradictions
    issues: list[str]             # Review issues

    # Budget
    total_llm_calls: int
    total_sources: int
    total_sub_queries: int
    budget_remaining: float       # Fraction of timeout remaining
```

### 2. Action Space

| Action | Method | When to use |
|--------|--------|-------------|
| `plan` | `_action_plan()` | Initial query or replanning |
| `gather` | `_action_gather()` | Need more sources |
| `analyze` | `_action_analyze()` | New sources need analysis |
| `synthesize` | `_action_synthesize()` | Enough analyzed sources |
| `report` | `_action_report()` | Synthesis ready |
| `review` | `_action_review()` | Report exists |
| `revise` | `_action_revise()` | Review failed |
| `done` | `_action_done()` | Quality达标 or budget耗尽 |

### 3. Reason Step (LLM Decision)

After each Observe, an LLM call decides the next action:

```python
async def _reason(self, state: ResearchState) -> str:
    """Ask LLM what to do next based on current state."""
    prompt = f"""
    Research topic: {state.query}
    Round: {state.round}/{state.max_rounds}
    Current phase: {state.phase}

    Current state:
    - Sub-queries: {len(state.sub_queries)} ({failed} failed)
    - Sources gathered: {len(state.sources)}
    - Sources analyzed: {analyzed_count}
    - Quality score: {state.quality_score}/10
    - Knowledge gaps: {state.knowledge_gaps}
    - Review issues: {state.issues}
    - Budget remaining: {state.budget_remaining:.0%}

    Available actions: plan, gather, analyze, synthesize, report, review, revise, done

    What should I do next? Return ONLY the action name.
    """
    return await self._call_llm(prompt)
```

**Decision rules (fallback if LLM unavailable):**

| Condition | Action |
|-----------|--------|
| No sub-queries yet | `plan` |
| Sub-queries exist, not all gathered | `gather` |
| All gathered, not all analyzed | `analyze` |
| All analyzed, no synthesis | `synthesize` |
| Synthesis ready, no report | `report` |
| Report exists, not reviewed | `review` |
| Review failed, rounds remaining | `revise` |
| Review passed or budget exhausted | `done` |
| Knowledge gaps detected, budget allows | `plan` (replan for gaps) |

### 4. ReAct Loop

```python
async def _react_loop(self, state: ResearchState) -> AsyncIterator[dict]:
    """Main ReAct loop."""
    while state.phase != "done":
        self._check_timeout()
        state.budget_remaining = 1 - (elapsed / timeout)

        # REASON: decide next action
        action = await self._reason(state)
        yield {"type": "reasoning", "action": action, "round": state.round}

        # ACT: execute action
        if action == "plan":
            async for event in self._action_plan(state):
                yield event
        elif action == "gather":
            async for event in self._action_gather(state):
                yield event
        elif action == "analyze":
            async for event in self._action_analyze(state):
                yield event
        elif action == "synthesize":
            async for event in self._action_synthesize(state):
                yield event
        elif action == "report":
            async for event in self._action_report(state):
                yield event
        elif action == "review":
            async for event in self._action_review(state):
                yield event
        elif action == "revise":
            async for event in self._action_revise(state):
                yield event
        elif action == "done":
            async for event in self._action_done(state):
                yield event
            break

        # OBSERVE: update state
        self._observe(state)

        # Check exit conditions
        if state.round >= state.max_rounds:
            yield {"type": "round_max", "round": state.round}
            async for event in self._action_done(state):
                yield event
            break
```

### 5. Observe Step

After each action, update state from DB:

```python
def _observe(self, state: ResearchState):
    """Refresh state from DB after action."""
    state.sources = self.db.get_sources(state.session_id)
    state.sub_queries = self.db.get_sub_queries(state.session_id)

    # Recalculate quality metrics
    analyzed = [s for s in state.sources if s.get("analysis")]
    state.total_sources = len(state.sources)
    state.total_sub_queries = len(state.sub_queries)

    # Check knowledge gaps from synthesis
    if state.synthesis:
        state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
        state.contradictions = state.synthesis.get("contradictions", [])
```

### 6. Action Implementations

#### `_action_plan()` — Initial or Re-planning

```python
async def _action_plan(self, state: ResearchState):
    state.phase = "planning"
    yield self._step_event("planning", "Planning sub-queries...")

    # If replanning: focus on knowledge gaps
    if state.knowledge_gaps:
        sub_queries = await self._plan_for_gaps(state.query, state.knowledge_gaps)
    else:
        sub_queries = await self._plan_sub_queries(state.query)

    # Deduplicate against existing sub-queries
    existing = {sq["query"] for sq in state.sub_queries}
    new_queries = [sq for sq in sub_queries if sq["query"] not in existing]

    for sq in new_queries:
        sq_id = self.session_manager.add_sub_query(state.session_id, sq["query"], sq["source_type"])
        sq["id"] = sq_id
        state.sub_queries.append(sq)
        yield {"type": "sub_query_created", ...}

    state.round += 1
```

#### `_action_gather()` — Search + Extract

```python
async def _action_gather(self, state: ResearchState):
    state.phase = "gathering"
    yield self._step_event("gathering", "Gathering sources...")

    # Only gather for sub-queries without sources
    gathered_ids = {s.get("sub_query_id") for s in state.sources}
    remaining = [sq for sq in state.sub_queries if sq["id"] not in gathered_ids]

    if remaining:
        gatherer = SourceGatherer(self.wiki, self.db, self.session_manager, self.config)
        events = await gatherer.gather(remaining)
        for event in events:
            yield event
```

#### `_action_analyze()` — LLM Analysis

```python
async def _action_analyze(self, state: ResearchState):
    state.phase = "analyzing"
    yield self._step_event("analyzing", "Analyzing sources...")

    sources = self.db.get_sources(state.session_id)
    unanalyzed = [s for s in sources if not s.get("analysis")]

    if unanalyzed:
        analyzer = SourceAnalyzer(self.wiki, self.session_manager, self.config)
        events = await analyzer.analyze_sources(unanalyzed)
        for event in events:
            yield event
```

#### `_action_synthesize()` — Cross-source Synthesis

```python
async def _action_synthesize(self, state: ResearchState):
    state.phase = "synthesizing"
    yield self._step_event("synthesizing", "Synthesizing findings...")

    sources = self.db.get_sources(state.session_id)
    synthesizer = ResearchSynthesizer(self.wiki, self.config)
    state.synthesis = await synthesizer.synthesize(sources)
    state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
    state.contradictions = state.synthesis.get("contradictions", [])

    yield {"type": "synthesis_complete", "synthesis": state.synthesis}
```

#### `_action_report()` — Generate Report

```python
async def _action_report(self, state: ResearchState):
    state.phase = "reporting"
    yield self._step_event("report", "Generating report...")

    sources = self.db.get_sources(state.session_id)
    generator = ReportGenerator(self.wiki, self._report_llm, self.config)
    state.report_md = await generator.generate(state.query, sources, state.synthesis)
```

#### `_action_review()` — Evaluate Quality

```python
async def _action_review(self, state: ResearchState):
    state.phase = "reviewing"
    yield self._step_event("review", "Reviewing report...")

    sources = self.db.get_sources(state.session_id)
    reviewer = ResearchReviewer(self.wiki, self._default_llm, self.config)
    state.review = await reviewer.review(state.query, state.report_md, sources)
    state.quality_score = state.review.get("score", 0)
    state.issues = state.review.get("issues", [])

    if state.review.get("approved"):
        yield {"type": "review_passed", "score": state.quality_score}
    else:
        yield {"type": "review_issues", "score": state.quality_score, "issues": state.issues}
```

#### `_action_revise()` — Fix Issues

```python
async def _action_revise(self, state: ResearchState):
    yield self._step_event("revise", "Revising report...")

    sources = self.db.get_sources(state.session_id)
    revisor = ResearchRevisor(self.wiki, self._report_llm, self.config)
    state.report_md = await revisor.revise(state.report_md, state.issues, sources)
```

#### `_action_done()` — Finalize

```python
async def _action_done(self, state: ResearchState):
    state.phase = "done"
    sources = self.db.get_sources(state.session_id)

    self.session_manager.finalize(state.session_id, {
        "markdown": state.report_md,
        "query": state.query,
    })

    yield {"type": "done", "report": {
        "query": state.query,
        "markdown": state.report_md,
        "sources": [...],
        "synthesis_summary": {...},
        "rounds": state.round,
        "quality_score": state.quality_score,
    }}
```

### 7. Re-planning for Knowledge Gaps

When synthesis reveals gaps, generate targeted sub-queries:

```python
async def _plan_for_gaps(self, query: str, gaps: list[str]) -> list[dict]:
    """Generate sub-queries to fill knowledge gaps."""
    prompt = f"""
    Research topic: {query}
    Knowledge gaps detected:
    {chr(10).join(f'- {gap}' for gap in gaps)}

    Generate 1-3 focused sub-queries to fill these gaps.
    Return JSON array with "query" and "source_type" fields.
    """
    # ... LLM call ...
```

### 8. DB Schema Changes

Add to `research_sessions`:

```sql
ALTER TABLE research_sessions ADD COLUMN iteration_round INTEGER DEFAULT 1;
ALTER TABLE research_sessions ADD COLUMN max_rounds INTEGER DEFAULT 5;
ALTER TABLE research_sessions ADD COLUMN knowledge_gaps TEXT;  -- JSON array
ALTER TABLE research_sessions ADD COLUMN quality_score INTEGER DEFAULT 0;
```

### 9. SSE Events

| Event | Type | When |
|-------|------|------|
| `reasoning` | new | Agent decides next action |
| `round_start` | new | New ReAct round begins |
| `round_end` | new | Round completes |
| `gap_detected` | new | Synthesis finds knowledge gaps |
| `replan` | new | Re-planning for gaps |
| `step` | existing | Stage transition |
| `sub_query_created` | existing | New sub-query |
| `source_gathered` | existing | Source fetched |
| `synthesis_complete` | existing | Synthesis done |
| `review_passed` | existing | Review approved |
| `review_issues` | existing | Review found issues |
| `done` | existing | Pipeline complete |

### 10. Frontend Changes

#### ResearchPanel.tsx — ReAct Loop Visualization

Replace fixed stage pipeline with adaptive loop display:

```
┌─ Round 2/5 ─────────────────────────────────────┐
│                                                  │
│  ✓ Plan → ✓ Gather → ✓ Analyze → ✓ Synthesize  │
│  → ● Review (score: 6/10)                       │
│                                                  │
│  Reasoning: "Score below threshold, revising"    │
│                                                  │
│  Knowledge gaps:                                 │
│  - leverage mechanism details                    │
│  - backtest performance data                     │
│                                                  │
│  Sources: 20 analyzed                            │
│  Quality: 6/10 (threshold: 7)                    │
└──────────────────────────────────────────────────┘
```

New components:
- `ReActRoundBar` — shows round progress within current round
- `ReasoningDisplay` — shows agent's decision
- `KnowledgeGapsList` — shows detected gaps
- `QualityScore` — shows score with threshold indicator

### 11. Configuration

```python
DEFAULT_RESEARCH_CONFIG = {
    # ... existing ...
    "max_react_rounds": 5,        # Max ReAct loops
    "quality_threshold": 7,       # Score >= 7 is approved
    "max_replan_attempts": 2,     # Max replanning for gaps
    "budget_per_round": 0.2,     # Fraction of timeout per round
}
```

### 12. Fallback Strategy

If LLM reasoning is unavailable (model failure, timeout):

```
1. Use deterministic rules (see "Decision rules" table above)
2. If rules can't decide → default to "done"
3. Always preserve ability to resume from any point
```

## Migration Path

### Phase 1: Add ReAct loop to engine.py
- Keep existing stage implementations (plan, gather, analyze, etc.)
- Wrap them in ReAct loop instead of sequential flow
- Add `_reason()` and `_observe()` methods
- Add `ResearchState` dataclass

### Phase 2: Add re-planning
- New prompt `research_replan.yaml`
- `_plan_for_gaps()` method
- DB schema migration

### Phase 3: Frontend updates
- `ReActRoundBar` component
- `ReasoningDisplay` component
- Updated SSE event handling

### Phase 4: Polish
- Budget tracking per round
- Adaptive timeout allocation
- Quality trend tracking across rounds

## Files to Modify

| File | Change |
|------|--------|
| `engine.py` | Rewrite `_run_stages()` → `_react_loop()` with `ResearchState` |
| `session.py` | Add `iteration_round`, `knowledge_gaps`, `quality_score` tracking |
| `db.py` | Add migration for new columns |
| `config.py` | Add `max_react_rounds`, `quality_threshold` |
| `prompts/_defaults/research_replan.yaml` | New prompt for gap-based replanning |
| `routes/research.py` | Add `reasoning`, `round_start/end`, `gap_detected` SSE events |
| `ResearchPanel.tsx` | ReAct loop visualization |
| `ResearchDetail.tsx` | Round history display |

## Estimated Effort

| Phase | Effort | Dependencies |
|-------|--------|-------------|
| Phase 1: ReAct loop | 2-3 days | None |
| Phase 2: Re-planning | 1 day | Phase 1 |
| Phase 3: Frontend | 1-2 days | Phase 1 |
| Phase 4: Polish | 1 day | Phase 1-3 |
| **Total** | **5-7 days** | |

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| LLM reasoning fails | Deterministic fallback rules |
| Too many rounds | `max_react_rounds` cap |
| Budget exhaustion | Per-round budget tracking |
| Regression | Keep existing stage implementations, just reorganize |
| DB migration | Additive only (new columns), no data loss |
