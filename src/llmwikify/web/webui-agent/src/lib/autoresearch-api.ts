/**
 * AutoResearch - API client for /api/autoresearch/* endpoints.
 *
 * v5: 6-step framework integration. Mirrors ppt-api.ts structure for
 * consistency. Used by AutoResearchPanel and AutoResearchDetail.
 */

const API_BASE = '/api/autoresearch';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 3000;

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  method: string,
  reqBody?: string,
): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    let response: Response;
    try {
      response = await fetch(url, init);
    } catch (e) {
      lastError = e;
      if (attempt < MAX_RETRIES) { await sleep(RETRY_DELAY_MS); continue; }
      throw e;
    }
    if (response.ok) return response;

    const text = await response.text();
    let parsed: { error?: string; detail?: unknown };
    try { parsed = JSON.parse(text); } catch { parsed = {}; }
    const msg = parsed.error
      || (Array.isArray(parsed.detail) && parsed.detail[0]?.msg)
      || `Failed (${response.status})`;
    if (attempt < MAX_RETRIES && response.status >= 500) {
      await sleep(RETRY_DELAY_MS);
      continue;
    }
    throw new Error(msg);
  }
  throw lastError instanceof Error ? lastError : new Error('Max retries exceeded');
}

// ─── Types ─────────────────────────────────────────────────────

export interface AutoResearchSession {
  id: string;
  wiki_id: string;
  query: string;
  status: string;
  current_step: string;
  progress: number;
  result: string | null;
  wiki_page_name: string | null;
  created_at: string;
  updated_at: string;
  clarification_json?: string | null;
  reasoning_json?: string | null;
  structure_json?: string | null;
  self_loop_counts_json?: string | null;
  self_loop_history_json?: string | null;
  evidence_scores_json?: string | null;
  synthesis_json?: string | null;
  review_json?: string | null;
  sub_queries?: AutoResearchSubQuery[];
  sources?: AutoResearchSource[];
  sub_query_count?: number;
  source_count?: number;
}

export interface AutoResearchSubQuery {
  id: string;
  session_id: string;
  query: string;
  source_type: string;
  url: string | null;
  status: string;
  result: unknown;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AutoResearchSource {
  id: string;
  session_id: string;
  sub_query_id: string;
  source_type: string;
  url: string;
  title: string;
  content_length: number;
  content_preview: string;
  analysis: unknown;
  rating: number | null;
  created_at: string;
}

/** Parsed 6-step framework fields. */
export interface AutoResearchSixStepFields {
  clarification: SixStepClarification | null;
  reasoning: SixStepReasoning | null;
  structure: SixStepStructure | null;
  self_loop_counts: Record<string, number> | null;
  self_loop_history: SixStepSelfLoopEntry[] | null;
  evidence_scores: Record<string, number> | null;
}

export interface SixStepClarification {
  context?: string;
  boundaries?: string;
  position?: string;
  premises?: string[];
  scope_check?: boolean;
  [key: string]: unknown;
}

export interface SixStepReasoning {
  aggregate_score: number;
  scores: Record<string, number>;
  issues: Array<{ dimension: string; severity: string; message: string }>;
  method?: string;
}

export interface SixStepStructure {
  aggregate_score: number;
  scores: Record<string, number>;
  issues: Array<{ layer: string; severity: string; message: string }>;
  method?: string;
}

export interface SixStepSelfLoopEntry {
  step: string;
  attempt: number;
  reason: string;
  timestamp?: string;
  [key: string]: unknown;
}

/** SSE stream event types (v5: 3 new). */
export type AutoResearchStreamEvent =
  | { type: 'step'; step: string; message: string; session_id?: string }
  | { type: 'reasoning'; action: string; thought?: string; round: number; phase: string }
  | { type: 'round_max'; round: number; message: string }
  | { type: 'gap_detected'; gaps: string[]; round: number }
  | { type: 'sub_query_created'; sub_query_id: string; query: string; source_type: string; url?: string }
  | { type: 'sub_query_done'; sub_query_id: string; status: string }
  | { type: 'sub_query_failed'; sub_query_id: string; error: string }
  | { type: 'source_gathered'; source_id: string; source_type: string; title: string; url: string }
  | { type: 'source_analyzed'; source_id: string; title: string }
  | { type: 'source_analysis_failed'; source_id: string; error: string }
  | { type: 'progress'; progress: number; message: string }
  | { type: 'synthesis_complete'; synthesis: Record<string, number> }
  | { type: 'clarification_complete'; round: number; scope_check: boolean; premises_count?: number; warnings?: string[]; context?: string }
  | { type: 'evidence_scoring_complete'; count: number; avg_score: number }  // v5
  | { type: 'reasoning_check_complete'; aggregate_score: number; issues_count: number }  // v5
  | { type: 'structure_check_complete'; aggregate_score: number; issues_count: number }  // v5
  | { type: 'review_passed'; round: number; score: number; feedback: string }
  | { type: 'review_issues'; round: number; score: number; issues: string[] }
  | { type: 'review_max_rounds'; message: string }
  | { type: 'cancelled'; round: number; phase: string }
  | { type: 'paused'; round: number; phase: string }
  | { type: 'done'; report: AutoResearchReport }
  | { type: 'error'; error: string };

export interface AutoResearchReport {
  query: string;
  markdown: string;
  sources: Array<{ id: string; title: string; url: string; source_type: string }>;
  synthesis_summary?: Record<string, number>;
  rounds?: number;
  quality_score?: number;
}

// ─── Helpers ──────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function parseSixStepFields(session: AutoResearchSession): AutoResearchSixStepFields {
  const parse = (raw: string | null | undefined): unknown => {
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  };
  return {
    clarification: parse(session.clarification_json) as SixStepClarification | null,
    reasoning: parse(session.reasoning_json) as SixStepReasoning | null,
    structure: parse(session.structure_json) as SixStepStructure | null,
    self_loop_counts: parse(session.self_loop_counts_json) as Record<string, number> | null,
    self_loop_history: parse(session.self_loop_history_json) as SixStepSelfLoopEntry[] | null,
    evidence_scores: parse(session.evidence_scores_json) as Record<string, number> | null,
  };
}

export { parseSixStepFields };

// ─── Public API ──────────────────────────────────────────────

/** Start a new 6-step autoresearch session. */
export async function startAutoResearch(
  query: string,
  wikiId?: string,
): Promise<{ sessionId: string; status: string }> {
  const url = `${API_BASE}/start`;
  const body = JSON.stringify({ query, wiki_id: wikiId });
  const response = await fetchWithRetry(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body,
  }, 'POST', body);
  const data = await response.json();
  return { sessionId: data.session_id, status: data.status };
}

/** List all autoresearch sessions (optionally filtered by wiki). */
export async function listAutoResearch(wikiId?: string): Promise<{
  autoresearch_sessions: AutoResearchSession[];
}> {
  const url = `${API_BASE}/list${wikiId ? `?wiki_id=${encodeURIComponent(wikiId)}` : ''}`;
  const response = await fetchWithRetry(url, {
    method: 'GET',
    headers: { ...authHeaders() },
  }, 'GET');
  return response.json();
}

/** Get a single session's full details (with parsed 6-step fields). */
export async function getAutoResearch(
  sessionId: string,
): Promise<{ session: AutoResearchSession; sixStep: AutoResearchSixStepFields }> {
  const url = `${API_BASE}/${sessionId}`;
  const response = await fetchWithRetry(url, {
    method: 'GET',
    headers: { ...authHeaders() },
  }, 'GET');
  const session: AutoResearchSession = await response.json();
  return { session, sixStep: parseSixStepFields(session) };
}

/** Pause a running session. */
export async function pauseAutoResearch(sessionId: string): Promise<{ paused: boolean }> {
  const url = `${API_BASE}/${sessionId}/pause`;
  const response = await fetchWithRetry(url, {
    method: 'POST',
    headers: { ...authHeaders() },
  }, 'POST');
  return response.json();
}

/** Resume a paused session; returns a fresh stream. */
export function resumeAutoResearch(
  sessionId: string,
): Promise<ReadableStream<AutoResearchStreamEvent>> {
  return new Promise((resolve, reject) => {
    const url = `${API_BASE}/${sessionId}/resume`;
    fetch(url, {
      method: 'POST',
      headers: { ...authHeaders() },
    })
      .then((res) => {
        if (!res.ok) {
          res.json().catch(() => ({})).then((b: { error?: string }) =>
            reject(new Error(b.error || `HTTP ${res.status}`))
          );
          return;
        }
        // The resume endpoint returns a stream response (SSE) — pass it through.
        resolve(sseStreamFromResponse(res));
      })
      .catch(reject);
  });
}

/** Delete (or cancel) a session. */
export async function deleteAutoResearch(
  sessionId: string,
): Promise<{ cancelled: boolean; session_id: string }> {
  const url = `${API_BASE}/${sessionId}`;
  const response = await fetchWithRetry(url, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  }, 'DELETE');
  return response.json();
}

/** Get only the clarification result (Step 1). */
export async function getClarification(
  sessionId: string,
): Promise<{ clarification: SixStepClarification | null; raw?: string }> {
  const url = `${API_BASE}/${sessionId}/clarification`;
  const response = await fetchWithRetry(url, {
    method: 'GET',
    headers: { ...authHeaders() },
  }, 'GET');
  return response.json();
}

// ─── SSE streaming (matches ppt-api streamPresentation style) ─

function sseStreamFromResponse(res: Response): ReadableStream<AutoResearchStreamEvent> {
  if (!res.body) {
    return new ReadableStream({
      start(controller) {
        controller.error(new Error('No response body'));
        controller.close();
      },
    });
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  return new ReadableStream<AutoResearchStreamEvent>({
    async start(controller) {
      let buffer = '';
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (line.startsWith('event: message')) continue;
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (data.trim()) {
                try {
                  const event = JSON.parse(data) as AutoResearchStreamEvent;
                  controller.enqueue(event);
                } catch { /* skip malformed */ }
              }
            }
          }
        }
        controller.close();
      } catch (e) {
        controller.error(e instanceof Error ? e : new Error(String(e)));
      }
    },
    cancel() {
      try { reader.cancel(); } catch { /* noop */ }
    },
  });
}

/**
 * Open an SSE stream for a session. Handles auto-reconnect (3 attempts)
 * with exponential backoff. Stops on 'done' event or when aborted.
 */
export function streamAutoResearch(
  sessionId: string,
  options: { signal?: AbortSignal } = {},
): ReadableStream<AutoResearchStreamEvent> {
  const url = `${API_BASE}/${sessionId}/stream`;
  const maxRetries = 3;

  return new ReadableStream<AutoResearchStreamEvent>({
    async start(controller) {
      let attempt = 0;
      const connect = async (): Promise<void> => {
        if (options.signal?.aborted) {
          controller.close();
          return;
        }
        try {
          const res = await fetch(url, {
            method: 'GET',
            headers: { ...authHeaders() },
            signal: options.signal,
          });
          if (!res.ok || !res.body) {
            if (attempt < maxRetries && res.status >= 500) {
              attempt++;
              await sleep(Math.min(1000 * Math.pow(2, attempt - 1), 8000));
              return connect();
            }
            controller.enqueue({ type: 'error', error: `HTTP ${res.status}` });
            controller.close();
            return;
          }

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let finished = false;

          while (!finished) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
              if (line.startsWith('event: message')) continue;
              if (line.startsWith('data: ')) {
                const data = line.slice(6);
                if (!data.trim()) continue;
                try {
                  const event = JSON.parse(data) as AutoResearchStreamEvent;
                  controller.enqueue(event);
                  if (event.type === 'done' || event.type === 'error') {
                    finished = true;
                    break;
                  }
                } catch { /* skip malformed */ }
              }
            }
          }
          controller.close();
        } catch (e) {
          if (options.signal?.aborted) {
            controller.close();
            return;
          }
          if (attempt < maxRetries) {
            attempt++;
            await sleep(Math.min(1000 * Math.pow(2, attempt - 1), 8000));
            return connect();
          }
          controller.enqueue({ type: 'error', error: String(e) });
          controller.close();
        }
      };
      await connect();
    },
    cancel() {
      if (options.signal && !options.signal.aborted) {
        // AbortSignal from fetch already supports throwIfAborted; if user
        // wants to forcibly cancel, they should use AbortController.abort().
        // No-op here since the connect loop checks signal.aborted.
      }
    },
  });
}
