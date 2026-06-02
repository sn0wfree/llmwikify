# StagePipeline UI Component Implementation Plan

> **Status:** ✅ Implemented
> **Last updated:** 2026-05-28
> **Note:** Superseded by `quick-research-display-language.md` and `react-research-engine.md` for current design.

## Overview

Replace the simple progress bar + stage description in research session cards with a
7-stage pipeline view that shows completed, current, and future stages with expandable
details for completed stages.

## Current State

Session cards currently show:
```
What is risk parity investing?              [gathering]
████████░░░░░░░░░░░░ 45%
Gathering sources — 15 sources collected
2m 30s | Updated 15s ago
[Resume] [Pause] [Delete]
```

## Target State

```
What is risk parity investing?              [gathering]

[✓] Planning ── 6 sub-queries
[✓] Gathering ─ 15 sources collected
[●] Analyzing ─ 25 sources
[ ] Synthesizing
[ ] Report
[ ] Review
[ ] Done

2m 30s | Updated 15s ago
[Resume] [Pause] [Delete]
```

Clicking a completed stage expands to show details (max 5 lines, indented):
```
[✓] Planning ── 6 sub-queries
    ├ risk parity investing definition (web)
    ├ risk parity vs traditional 60/40 (web)
    ├ risk parity implementation methods (web)
    ├ risk parity performance history (web)
    ├ leverage in risk parity explained (web)
    └ advantages criticisms limitations (web)
```

## Stage Pipeline

7 stages in order:
1. **Planning** — decompose query into sub-queries
2. **Gathering** — fetch content from web sources
3. **Analyzing** — analyze source content via LLM
4. **Synthesizing** — cross-source synthesis with rating weighting
5. **Report** — generate structured markdown report
6. **Reviewing** — evaluate report quality
7. **Done** — finalize

## Stage Status

```
✓ = completed (gray, clickable to expand)
● = current (highlighted blue, pulsing dot)
○ = pending (light gray, not clickable)
```

## Stage Result Descriptions

| Stage | Description | Data Source |
|-------|-------------|-------------|
| planning | `{n} sub-queries` | session.sub_query_count |
| gathering | `{n} sources collected` | session.source_count |
| analyzing | `{n} sources analyzed` | session.source_count |
| synthesizing | "Complete" / "Synthesizing..." | session.status |
| report | "Report generated" / "Generating..." | session.result |
| reviewing | "Passed (score X)" / "Reviewing..." | session.status |
| done | "Complete" | session.status |

## Expandable Details

Each completed stage can be expanded to show details (max 5 lines, indented):

| Stage | Expand Content |
|-------|----------------|
| planning | List sub-queries: `{query} ({source_type})` |
| gathering | List sources: `{title} ({source_type})` |
| analyzing | List analyzed sources with credibility score |
| synthesizing | reinforced_claims, contradictions, knowledge_gaps counts |
| report | Report length + sources cited count |
| reviewing | Review round + score + issues |

## Component Structure

```tsx
// StagePipeline.tsx (new component)
interface StagePipelineProps {
  session: ResearchSession;
}

// StageItem sub-component
interface StageItemProps {
  stage: string;
  status: 'completed' | 'current' | 'pending';
  result: string;
  details?: string[];  // expandable content
  expanded: boolean;
  onToggle: () => void;
}
```

## Visual Design

- Pipeline line: vertical line connecting stages (2px, gray)
- Stage icons: ✓ (checkmark), ● (filled circle), ○ (empty circle)
- Completed stages: gray text, cursor pointer, hover underline
- Current stage: blue text, animated pulse on ●
- Pending stages: light gray text, no interaction
- Expand animation: slide down with transition
- Detail lines: indented 16px, monospace font, max 5 lines with scroll

## Files to Modify

| File | Change |
|------|--------|
| `ResearchPanel.tsx` | Add `StagePipeline` + `StageItem` components, replace stage description in session cards |
| `ResearchDetail.tsx` | Replace Progress section with `StagePipeline` component |

## Implementation Steps

1. Create `StagePipeline` component with `StageItem` sub-component
2. Implement stage status calculation logic
3. Implement stage result description logic
4. Implement expandable details with max 5 lines
5. Replace in ResearchPanel session cards
6. Replace in ResearchDetail Progress section
7. Build and verify no TypeScript errors
8. Run tests to verify no regressions

## Dependencies

- No new npm packages needed
- Uses existing `ResearchSession` type from `api.ts`
- Uses existing `ResearchSubQuery` and `ResearchSource` types for details

## Testing

- Visual verification: render session cards with different statuses
- Expand/collapse: click completed stages to toggle details
- Build: `npx vite build` passes
- Tests: `pytest tests/test_research.py` passes (90 tests)
