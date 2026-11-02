/**
 * The research run status shape.
 *
 * It is shared by the REST endpoints (`/api/agent/research-runs/...`)
 * and by the `research_run_started` SSE event — the backend emits the
 * same object on both channels, so the type lives in one place.
 *
 * The generated SSE union (`src/generated/events.ts`) imports it from
 * here; `src/api.ts` re-exports it for the existing call sites.
 */

export interface ResearchRunTimelineItem {
  phase_id: string;
  label: string;
  status: string;
}

export interface ResearchRunStatus {
  run_id: string;
  workflow_name?: string;
  status: string;
  timeline: ResearchRunTimelineItem[];
  artifact_counts?: Record<string, number>;
  proposal_bundle?: unknown;
  writes_wiki?: boolean;
  proposal_only?: boolean;
  started_at?: number;
  last_updated?: number;
  total_tokens_used?: number;
  total_agents_spawned?: number;
  error?: string;
}
