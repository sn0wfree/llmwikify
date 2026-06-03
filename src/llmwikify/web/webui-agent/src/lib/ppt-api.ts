/**
 * PPT Generator - API client for backend endpoints
 */

const API_BASE = '/api/ppt';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 3000;

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

function isFrpsError(response: Response, body: string): boolean {
  return response.status === 404
    && (response.headers.get('content-type') || '').includes('text/html')
    && body.includes('frp');
}

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
      reportFetchError(url, e, method);
      throw e;
    }

    if (response.ok) return response;

    const text = await response.text();

    if (isFrpsError(response, text) && attempt < MAX_RETRIES) {
      reportApiError(response, text, method, reqBody);
      await sleep(RETRY_DELAY_MS);
      continue;
    }

    reportApiError(response, text, method, reqBody);
    let parsed: { error?: string };
    try { parsed = JSON.parse(text); } catch { parsed = {}; }
    throw new Error(parsed.error || `Failed (${response.status})`);
  }
  throw lastError instanceof Error ? lastError : new Error('Max retries exceeded');
}

function reportApiError(response: Response, body: string, method: string, requestBody?: string) {
  fetch('/api/log/error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'api-error',
      status: response.status,
      method,
      url: response.url,
      requestBody: requestBody?.slice(0, 200),
      contentType: response.headers.get('content-type'),
      bodySnippet: body.slice(0, 500),
    }),
  }).catch(() => {})
}

function reportFetchError(endpoint: string, error: unknown, method: string = 'GET') {
  fetch('/api/log/error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'fetch-error',
      status: 0,
      method,
      url: window.location.href,
      endpoint,
      message: error instanceof Error ? error.message : String(error),
    }),
  }).catch(() => {})
}

export interface OutlinePage {
  page: number;
  content_type: string;
  title: string;
  description: string;
}

export interface Outline {
  title: string;
  subtitle?: string;
  pages: OutlinePage[];
}

// v0.6.1: Re-export the comprehensive Theme from ppt-themes.ts so we
// have a single source of truth for the type. The legacy Theme/ThemeColors
// interfaces defined here are kept for backward compatibility (they're
// structurally identical to the .colors subset of the new Theme).
export type { Theme, ThemeCategory } from './ppt-themes';
export { CATEGORY_LABELS, CATEGORY_ORDER, LEGACY_ALIASES, THEMES } from './ppt-themes';
import type { Theme } from './ppt-themes';

export interface SlideContent {
  id: string;
  layout: string;
  title: string;
  subtitle?: string;
  content?: string;
  bullets?: string[];
  left?: { heading: string; items: string[] };
  right?: { heading: string; items: string[] };
  chart_type?: string;
  chart_data?: { labels: string[]; values: number[] };
  text?: string;
  author?: string;
  image?: string;
  // Extended layout fields (v0.7)
  swot?: { strengths: string[]; weaknesses: string[]; opportunities: string[]; threats: string[] };
  table_headers?: string[];
  table_rows?: string[][];
  events?: { date: string; title: string; description?: string }[];
  kpi_items?: { label: string; value: string; trend?: string }[];
  central_topic?: string;
  branches?: { name: string; children?: { name: string }[] }[];
  steps?: { title: string; description?: string }[];
  images?: { url: string; caption?: string }[];
  html?: string;
}

export interface Presentation {
  title: string;
  subtitle?: string;
  theme: Theme;
  slides: SlideContent[];
  source: { type: string };
}

export interface OutlineResponse {
  outline: Outline;
}

export interface GenerateResponse {
  presentation: Presentation;
  model_used: string;
  generation_time_ms: number;
}

export interface FromSourceResponse {
  outline: Outline;
  source_summary: string;
  source_count: number;
}

export interface ThemesResponse {
  themes: Theme[];
}

/**
 * Generate outline from topic (Step 1)
 */
export async function generateOutline(
  topic: string,
  numSlides: number = 8,
  language: string = 'zh'
): Promise<OutlineResponse> {
  const endpoint = `${API_BASE}/outline`;
  const reqBody = JSON.stringify({ topic, num_slides: numSlides, language });
  const response = await fetchWithRetry(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  }, 'POST', reqBody);
  return response.json();
}

/**
 * Generate content based on outline (Step 2) — sync (legacy)
 */
export async function generatePresentation(
  outline: Outline,
  theme: string = 'professional',
  language: string = 'zh'
): Promise<GenerateResponse> {
  const endpoint = `${API_BASE}/generate`;
  const reqBody = JSON.stringify({ outline, theme, language });
  const response = await fetchWithRetry(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  }, 'POST', reqBody);
  return response.json();
}

// ─── Async Generation + SSE Streaming ───────────────────────────────

export interface SlideStartEvent {
  type: 'slide_start';
  index: number;
  total: number;
  title: string;
}

export interface SlideDoneEvent {
  type: 'slide_done';
  index: number;
  total: number;
  slide: SlideContent;
}

export interface SlideErrorEvent {
  type: 'slide_error';
  index: number;
  total: number;
  error: string;
}

export interface DoneEvent {
  type: 'done';
  presentation: GenerateResponse;
}

export interface ErrorEvent {
  type: 'error';
  error: string;
}

export type PPTStreamEvent = SlideStartEvent | SlideDoneEvent | SlideErrorEvent | DoneEvent | ErrorEvent;

/**
 * Start async PPT content generation (Step 2).
 * Returns task_id immediately (< 1s). Use streamPresentation() to get progress.
 */
export async function generatePresentationAsync(
  outline: Outline,
  theme: string = 'professional',
  language: string = 'zh',
  sourceType?: string,
  sourceId?: string,
): Promise<{ task_id: string }> {
  const endpoint = `${API_BASE}/generate`;
  const reqBody = JSON.stringify({
    outline, theme, language,
    source_type: sourceType,
    source_id: sourceId,
  });
  const response = await fetchWithRetry(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  }, 'POST', reqBody);
  const data = await response.json();
  return { task_id: data.task_id };
}

/**
 * SSE stream of PPT generation progress.
 *
 * v0.5: Adds automatic reconnect with exponential backoff (1s -> 2s -> 4s -> 8s,
 * capped at 8s) to survive transient disconnects (e.g., frps 60s timeout).
 * Stops reconnecting after 5 failed attempts, surfacing the error to the caller.
 * Stops immediately when:
 *   - the 'done' event is received
 *   - the AbortController is aborted
 *   - 5 consecutive reconnects fail
 */
export function streamPresentation(
  taskId: string,
  callbacks: {
    onSlideStart?: (event: SlideStartEvent) => void;
    onSlideDone?: (event: SlideDoneEvent) => void;
    onSlideError?: (event: SlideErrorEvent) => void;
    onDone?: (event: DoneEvent) => void;
    onError?: (event: ErrorEvent) => void;
    onReconnecting?: (attempt: number, nextDelayMs: number) => void;
  },
): AbortController {
  const controller = new AbortController();
  const url = `${API_BASE}/task/${taskId}/stream`;
  let stopped = false;
  let receivedDone = false;
  let backoff = 1000;
  const MAX_RECONNECTS = 5;
  let reconnectAttempts = 0;

  function sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function connect(): Promise<void> {
    while (!stopped && !receivedDone) {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`SSE connection failed (${response.status}): ${text}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        // Reset backoff on successful connect
        backoff = 1000;
        reconnectAttempts = 0;

        while (!stopped && !receivedDone) {
          const { done, value } = await reader.read();
          if (done) {
            // Stream ended without 'done' event — likely a network drop
            throw new Error('SSE stream ended unexpectedly');
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          let eventData = '';

          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              eventData = line.slice(5).trim();
            } else if (line === '' && eventData) {
              try {
                const parsed = JSON.parse(eventData);
                switch (parsed.type) {
                  case 'slide_start':
                    callbacks.onSlideStart?.(parsed as SlideStartEvent);
                    break;
                  case 'slide_done':
                    callbacks.onSlideDone?.(parsed as SlideDoneEvent);
                    break;
                  case 'slide_error':
                    callbacks.onSlideError?.(parsed as SlideErrorEvent);
                    break;
                  case 'done':
                    receivedDone = true;
                    callbacks.onDone?.(parsed as DoneEvent);
                    return; // Exit the connect loop
                  case 'error':
                    callbacks.onError?.(parsed as ErrorEvent);
                    break;
                }
              } catch {
                // Skip unparseable events
              }
              eventType = '';
              eventData = '';
            }
          }
        }
        return; // Normal exit (stopped or done)
      } catch (e) {
        if (stopped || (e as Error).name === 'AbortError') return;
        if (receivedDone) return;

        reconnectAttempts += 1;
        if (reconnectAttempts > MAX_RECONNECTS) {
          callbacks.onError?.({
            type: 'error',
            error: `Connection failed ${MAX_RECONNECTS} times. Task may still be running on the server — check the sidebar.`,
          });
          return;
        }

        callbacks.onReconnecting?.(reconnectAttempts, backoff);
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 8000);
      }
    }
  }

  // Start the connect loop without blocking
  connect().catch((e) => {
    if (!stopped) {
      callbacks.onError?.({ type: 'error', error: String(e) });
    }
  });

  return {
    abort: () => {
      stopped = true;
      controller.abort();
    },
  } as AbortController;
}

/**
 * Generate outline from Quick Research results
 */
export async function generateFromResearch(
  researchId: string,
  theme: string = 'professional',
  language: string = 'zh'
): Promise<FromSourceResponse> {
  const endpoint = `${API_BASE}/from-research`;
  const reqBody = JSON.stringify({ research_id: researchId, theme, language });
  const response = await fetchWithRetry(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  }, 'POST', reqBody);
  return response.json();
}

/**
 * Generate outline from Chat conversation
 */
export async function generateFromChat(
  chatSessionId: string,
  theme: string = 'professional',
  language: string = 'zh'
): Promise<FromSourceResponse> {
  const endpoint = `${API_BASE}/from-chat`;
  const reqBody = JSON.stringify({ chat_session_id: chatSessionId, theme, language });
  const response = await fetchWithRetry(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  }, 'POST', reqBody);
  return response.json();
}

/**
 * Get list of available themes
 */
export async function getThemes(): Promise<ThemesResponse> {
  const endpoint = `${API_BASE}/themes`;
  const response = await fetchWithRetry(endpoint, { method: 'GET' }, 'GET');
  return response.json();
}

// ─── Task List / Get / Delete (v0.5) ─────────────────────────────

export type TaskStatus = 'pending' | 'running' | 'done' | 'error';
export type SourceType = 'topic' | 'research' | 'chat';

export interface PPTTaskSummary {
  id: string;
  title: string | null;
  subtitle: string | null;
  theme: string;
  source_type: SourceType | null;
  source_id: string | null;
  status: TaskStatus;
  error: string | null;
  slide_count: number;
  model_used: string | null;
  generation_time_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface ListTasksResponse {
  tasks: PPTTaskSummary[];
}

export interface GetTaskResponse {
  task_id: string;
  status: TaskStatus;
  presentation?: { presentation: Presentation };
  error?: string;
}

/**
 * List past PPT tasks for the sidebar.
 * @param limit Max tasks to return (default 50)
 * @param sourceType Optional filter — 'topic' | 'research' | 'chat'
 */
export async function listTasks(
  limit: number = 50,
  sourceType?: SourceType,
): Promise<ListTasksResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (sourceType) params.set('source_type', sourceType);
  const endpoint = `${API_BASE}/tasks?${params.toString()}`;
  const response = await fetchWithRetry(endpoint, { method: 'GET' }, 'GET');
  return response.json();
}

/**
 * Get a single task by ID (includes presentation if done).
 * Used for refresh recovery and for clicking a sidebar item.
 */
export async function getTask(taskId: string): Promise<GetTaskResponse> {
  const endpoint = `${API_BASE}/task/${taskId}`;
  const response = await fetchWithRetry(endpoint, { method: 'GET' }, 'GET');
  return response.json();
}

/**
 * Delete a task. Removes the DB row and any in-memory state.
 * Use when user clicks the × button on a sidebar item.
 */
export async function deleteTask(taskId: string): Promise<{ ok: boolean }> {
  const endpoint = `${API_BASE}/task/${taskId}`;
  const response = await fetchWithRetry(
    endpoint, { method: 'DELETE' }, 'DELETE',
  );
  return response.json();
}

// ─── PPTChat SSE Streaming ─────────────────────────────────

export interface PPTChatStreamEvent {
  type: 'session_created' | 'thinking' | 'message_delta' | 'tool_start' | 'tool_end' | 'done' | 'error';
  session_id?: string;
  content?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  updated_presentation?: Presentation;
  message?: string;
  error?: string;
}

/**
 * Stream PPTChat messages via SSE.
 * Returns a ReadableStreamDefaultReader for consuming events.
 */
export async function pptChatStream(params: {
  message: string;
  task_id: string;
  current_slide_index: number;
  session_id?: string;
}): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const endpoint = `${API_BASE}/chat`;
  const reqBody = JSON.stringify(params);
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`PPT Chat failed (${response.status}): ${text}`);
  }

  if (!response.body) {
    throw new Error('No response body');
  }

  return response.body.getReader();
}

/**
 * Get chat messages for a PPTChat session.
 */
export async function getPptChatMessages(
  sessionId: string,
  limit: number = 50,
): Promise<{ messages: Array<{ role: string; content: string; created_at: string }> }> {
  const endpoint = `${API_BASE}/chat/sessions/${sessionId}/messages?limit=${limit}`;
  const response = await fetchWithRetry(endpoint, { method: 'GET' }, 'GET');
  return response.json();
}

export default {
  generateOutline,
  generatePresentation,
  generatePresentationAsync,
  streamPresentation,
  generateFromResearch,
  generateFromChat,
  getThemes,
  listTasks,
  getTask,
  deleteTask,
  pptChatStream,
  getPptChatMessages,
};
