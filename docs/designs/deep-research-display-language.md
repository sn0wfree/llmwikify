# Quick Research Display Language — Design Document

## Overview

Redesign the Quick Research UI to provide **semantic progress**, **structural event display**, and **rich source tracking**. Replaces flat event lists with layered, meaningful visual feedback.

> **Status:** ✅ Implemented (Phase 1-3 complete)
> **Last updated:** 2026-05-28

## Goal

Transform the research panel from a technical debug view into an intuitive research cockpit where users can immediately understand:
- **What is happening right now**
- **How much progress has been made** (in human terms)
- **Where each source stands**
- **Which ReAct round and quality score** (after ReAct engine upgrade)

## Current vs Target

### Active Panel: Before → After

**Before:**
```
Status: gathering (gathering) — 45%
[web] risk parity definition          ⟳
[web] risk parity vs 60/40 allocation  ✓
[pdf] AQR Risk Parity Paper            ⟳
...
Latest: "Gathered source: AQR Risk Parity Paper"
Latest: "Gathered source: Fed Paper"
Latest: "Sub-query done: risk parity definition"
```

**After:**
```
●━━━●━━━○━━━○━━━○━━━○━━━○   ← 7-stage mini bar
 Planning  Gathering  Analyzing  Report  Done

Gathering ── 4/6 queries done · 12 sources     ← semantic status line

┌──┐ ┌──┐ ┌──┐ ┌──┐ +3                         ← source site cards
│AQR│ │FED│ │WIK│ │MSF│
└──┘ └──┘ └──┘ └──┘

▶ risk parity definition (web)        ✓ done   ← collapsible sub-queries
✓ risk parity vs 60/40 allocation...  ✓ done
◐ risk parity implementation methods  ◐ fetching
```

### Session Cards: Before → After

**Before:**
```
What is risk parity investing?         [gathering]
[✓] Planning ── 6 sub-queries
[✓] Gathering ─ 15 sources collected
[●] Analyzing ─ 25 sources
...
2m 30s | Updated 15s ago | 34df09a7
```

**After:**
```
What is risk parity investing?         [gathering]

●━━━●━━━○━━━○━━━○━━━○━━━○   ← mini stage bar
 Planning  Gathering  Analyzing  Report  Done

Gathering ── 4/6 queries · 12 sources         ← semantic line
Analyzing ── 25 sources ████░░░░░░             ← credibility bar

2m 30s elapsed · Updated 15s ago · 34df09a7
[Resume]  [Pause]  [Delete]
```

## Design Language

### Color Palette

```css
/* Stage states */
--stage-completed: var(--text-secondary);
--stage-current: var(--accent);
--stage-pending: var(--text-secondary);
--stage-connector: var(--border);

/* Credibility */
--cred-high: #22c55e;
--cred-mid: #eab308;
--cred-low: #ef4444;

/* Source cards */
--source-bg: var(--bg-tertiary);
--source-border: var(--border);

/* Event stream */
--event-latest: var(--accent);
--event-normal: var(--text-secondary);

/* Pulse animation (current stage) */
@keyframes stage-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 currentColor; }
  50% { opacity: 0.75; box-shadow: 0 0 0 3px currentColor; }
}
```

### Typography

- Stage labels: `text-xs font-medium`
- Stage result: `text-xs text-secondary`
- Sub-query text: `text-xs`
- Event text: `text-[11px]`
- Source domains: `text-[10px] font-mono`

### Spacing

- StagePipeline row height: `h-6` (compact)
- Stage connector: `h-1.5`
- Source card: `w-8 h-8 rounded`
- Sub-query indent: `pl-4`

## Components

### 1. MiniStageBar

7-segment horizontal bar showing pipeline completion at a glance.

```tsx
interface MiniStageBarProps {
  currentStep: string;
  status: string;
  stages?: string[]; // default: STAGES
}

// Rendering:
// For each stage:
//   - completed (before currentStep): filled segment (--accent with 40% opacity)
//   - current: filled + pulsing ring
//   - pending: empty segment (border only)
```

**Visual:** `●━━━●━━━○━━━○━━━○━━━○━━━○` — filled circle = completed, ring = current, empty = pending

### 2. SourceCard (NEW)

Favicon + domain chip for tracking live source fetches.

```tsx
interface SourceCardProps {
  title: string;
  domain: string;
  status: 'pending' | 'fetching' | 'done' | 'failed';
  credibility?: number;
  favicon?: string;
}
```

**Visual:**
```
┌────┐
│ 🌐 │  ← favicon or first letter
│ fed │  ← domain label
└────┘
```

States: fetching = spinner overlay, done = checkmark badge, failed = red X badge

### 3. StageStatusLine

Semantic progress line replacing raw percentage.

```tsx
interface StageStatusLineProps {
  stage: string;
  session: ResearchSession;
}
```

| Stage | Content |
|-------|---------|
| planning | `Planning — decomposing into {n} sub-queries` |
| gathering | `Gathering — {done}/{total} queries · {sources} sources` |
| analyzing | `Analyzing — {n} sources ████░░░░░░` (credibility bar) |
| synthesizing | `Synthesizing — {claims} findings · {contradictions} gaps` |
| report | `Report — {chars} chars generated` (streaming) |
| reviewing | `Review — round {n}/{max}, score {score}` |
| done | `Done — {chars} chars · {sources} sources` |

### 4. SubQueryRow (collapsible)

Sub-query with status icon, source type badge, collapsible details.

```tsx
interface SubQueryRowProps {
  subQuery: ResearchSubQuery;
  expanded: boolean;
  onToggle: () => void;
}
```

**Default state (collapsed, done):** Shows checkmark + domain + truncated query
**Expanded:** Shows full query + URL + result snippet

### 5. SourceTooltip

Hover card showing source preview.

### 6. CitationHover

`[[Source:hash]]` hover reveals source card.

## Active Panel Layout

```
┌─ 正在研究：{query} [gathering] ────────────────┐
│ [Pause]  [Dismiss]                             │
├───────────────────────────────────────────────┤
│                                               │
│  ●━━━●━━━○━━━○━━━○━━━○━━━○                    │ ← MiniStageBar (7-seg)
│  Planning  Gathering  Analyzing  Report  Done │
│                                               │
│  Round 2/5  Quality: 6/10  → gather           │ ← ReAct info
│                                               │
│  Gathering ── 4/6 queries · 12 sources        │ ← StageStatusLine
│                                               │
│  Knowledge Gaps (2)                           │ ← Yellow warning
│  · leverage mechanism details                 │
│  · backtest performance data                  │
│                                               │
│  ┌──┐ ┌──┐ ┌──┐ ┌──┐ +3                      │ ← SourceCardGrid
│  │🌐│ │📄│ │🌐│ │📄│                          │
│  └──┘ └──┘ └──┘ └──┘                          │
│                                               │
│  Sub-queries:                                 │ ← Collapsible
│  ▶ risk parity definition (web)    ✓          │
│  ✓ risk parity vs 60/40...        ✓          │
│  ◐ implementation methods          ◐          │
│                                               │
│  ▶ Decision: gather                           │ ← Latest event
│                                               │
│  [Pause]  [Cancel]                            │
└───────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Core Components ✅

1. **MiniStageBar** — compact 7-segment bar with pulse animation
2. **StageStatusLine** — semantic progress text using actual source counts
3. **SourceCard** — favicon + domain chip with hover tooltip + type badges
4. **SubQueryRow** — collapsible with type badge colors (web/pdf/arxiv/wiki/youtube)
5. **Active panel redesign** — integrate above into `ResearchPanel.tsx`
6. **Session card enhancement** — mini bar + semantic lines + done summary

### Phase 2: Interactions ✅

7. SourceCard hover tooltip — full title, type badge, domain
8. SourceCardGrid — expand "+N" button, entrance animation
9. SubQueryRow — URL link display, type badge colors

### Phase 3: Polish ✅

10. Pulse animation (`@keyframes stage-pulse`) for current stage
11. Collapsible report preview in active panel
12. Empty state with icon + example queries
13. Error state with warning icon + retry support
14. Knowledge gaps display (yellow warning box)

### Phase 4: ReAct Integration ✅

15. Round counter (Round 2/5)
16. Quality score display (Quality: 6/10, color-coded)
17. Reasoning action display (→ gather)
18. Knowledge gaps list from synthesis
19. New SSE events: reasoning, round_max, gap_detected

## Files Modified

| File | Change | Status |
|------|--------|--------|
| `ResearchPanel.tsx` | MiniStageBar, StageStatusLine, SourceCard, SubQueryRow, SourceCardGrid, EmptyState, ErrorState, ReAct display | ✅ |
| `ResearchDetail.tsx` | Uses MiniStageBar, semantic status lines | ✅ |
| `ResearchRating.tsx` | Source card integration | ✅ |
| `api.ts` | ResearchStreamEvent types including ReAct events | ✅ |
| `styles/index.css` | stage-pulse, source-enter animations | ✅ |

## Key Technical Decisions

1. **No new npm packages** — pure CSS + Tailwind animations
2. **MiniStageBar uses CSS custom properties** for pulse color inheritance
3. **SourceCard favicon** — use first letter as placeholder, no external fetch initially
4. **SubQueryRow collapse** — CSS max-h transition, no JS animation library
5. **Credibility bar** — 10-segment Unicode bar `█▓▒░` or CSS div segments
6. **SSE event handling** — extend `handleStreamEvent` to emit SourceCard events

## Color Mapping (Tailwind)

```tsx
// Stage status
const stageColor = {
  completed: 'text-[var(--text-secondary)]',
  current: 'text-[var(--accent)]',
  pending: 'text-[var(--text-secondary)] opacity-30',
  error: 'text-red-400',
};

// Source card border
const sourceBorder = {
  pending: 'border-[var(--border)]',
  fetching: 'border-yellow-500/50',
  done: 'border-green-500/50',
  failed: 'border-red-500/50',
};

// Credibility bar (10 segments)
const credSegments = (cred: number) => {
  const filled = Math.round(cred * 10);
  return '█'.repeat(filled) + '░'.repeat(10 - filled);
};
```
