const API_BASE = '/api';
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

export type ChatStreamEvent =
  | { type: 'session_created'; session_id: string }
  | { type: 'message_delta'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call_start'; tool: string; args: Record<string, unknown>; call_id: string }
  | { type: 'tool_call_end'; tool: string; result: unknown; call_id: string; duration_ms: number }
  | { type: 'tool_call_error'; tool: string; error: string; call_id: string; duration_ms: number }
  | { type: 'done'; final_response: string }
  | { type: 'save_warning'; reason: string }
  | { type: 'confirmation_required'; confirmation_id: string; tool: string; args: Record<string, unknown>; impact: Record<string, unknown>; call_id: string; duration_ms: number }
  | { type: 'error'; message: string };

// Phase 5.4 (v0.36): SSE reconnection configuration.
const SSE_MAX_RETRIES = 3;
const SSE_RETRY_DELAYS = [1000, 2000, 4000]; // ms, exponential

function isRetryableError(error: unknown): boolean {
  // Network errors and 5xx responses are retryable.
  if (error instanceof TypeError && error.message.includes('fetch')) return true;
  if (error instanceof Error && error.message.includes('network')) return true;
  // AbortError (user-initiated) is NOT retryable.
  if (error instanceof DOMException && error.name === 'AbortError') return false;
  // 429 (rate limit) and 5xx are retryable.
  if (error instanceof Error && /429|5[0-9]{2}/.test(error.message)) return true;
  return false;
}

export function chatStream(
  message: string,
  sessionId?: string,
  wikiId?: string,
  signal?: AbortSignal,
  attachments?: Array<{ name: string; mime: string; data: string }>,
): ReadableStream<ChatStreamEvent> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (API_TOKEN) {
    headers['Authorization'] = `Bearer ${API_TOKEN}`;
  }

  return new ReadableStream<ChatStreamEvent>({
    async start(controller) {
      try {
        const res = await fetch(`${API_BASE}/agent/chat`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ message, session_id: sessionId, wiki_id: wikiId, attachments }),
          signal,
        });

        if (!res.ok) {
          let errorMessage = `API error: ${res.status}`;
          try {
            const body = await res.json();
            errorMessage = body.error || body.message || body.detail || errorMessage;
          } catch { /* ignore */ }
          controller.error(new Error(errorMessage));
          return;
        }

        if (!res.body) {
          controller.error(new Error('No response body'));
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

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
                  const event = JSON.parse(data) as ChatStreamEvent;
                  controller.enqueue(event);
                } catch { /* ignore parse errors */ }
              }
            }
          }
        }
        controller.close();
      } catch (e) {
        // Phase 5.1 (v0.36): abort errors are expected when the
        // user clicks Stop. Don't propagate them as stream errors.
        if (e instanceof DOMException && e.name === 'AbortError') {
          controller.close();
          return;
        }
        // Phase 5.4 (v0.36): non-retryable errors propagate.
        controller.error(e instanceof Error ? e : new Error(String(e)));
      }
    },
  });
}

export interface WikiPage {
  page_name: string;
  content: string;
  file: string;
  is_sink: boolean;
  has_sink?: boolean;
  sink_entries?: number;
}

export interface SearchResult {
  page_name: string;
  content: string;
  snippet?: string;
  score: number;
  has_sink?: boolean;
  sink_entries?: number;
  page_type?: string;
}

export interface WikiStatus {
  page_count: number;
  sink_entries: number;
  db_path: string;
  is_initialized: boolean;
  all_types?: string[];
  pages_by_type?: Record<string, string[]>;
  root?: string;
  version?: string;
}

export interface SinkStatus {
  total_entries: number;
  total_sinks: number;
  urgent_count: number;
  sinks: Array<{
    page_name: string;
    entry_count: number;
    urgency: string;
  }>;
}

export interface AgentMessage {
  role: string;
  content: string;
  timestamp?: string;
}

export interface TaskInfo {
  name: string;
  cron_expr: string;
  description: string;
  enabled: boolean;
  last_run: string | null;
  next_run: string | null;
  run_count: number;
}

export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  timestamp: string;
  read: boolean;
}

export interface DreamEdit {
  timestamp: string;
  sinks_processed: number;
  edits_applied: number;
  edits: Array<{
    page: string;
    edit_count: number;
    status: string;
  }>;
  errors: Array<{ page: string; error: string }>;
}

export interface DreamProposal {
  id: string;
  page_name: string;
  edit_type: string;
  content: string;
  reason: string;
  content_length: number;
  status: string;
  created_at: string;
  reviewed_at: string | null;
}

export interface Confirmation {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  action_type: string;
  impact: Record<string, unknown>;
  group: string;
  created_at: string;
  status: string;
}

export interface IngestLogEntry {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  timestamp: string;
  status: string;
}

export interface GraphNode {
  id: string;
  label: string;
  in_degree: number;
  out_degree: number;
  is_current: boolean;
  page_type: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: {
    total_nodes: number;
    displayed_nodes: number;
    mode: string;
  };
  all_types: string[];
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (API_TOKEN) {
    headers['Authorization'] = `Bearer ${API_TOKEN}`;
  }
  const res = await fetch(`${API_BASE}${endpoint}`, { headers, ...options });
  if (!res.ok) {
    let errorMessage = `API error: ${res.status}`;
    try {
      const body = await res.json();
      errorMessage = body.error || body.message || body.detail || errorMessage;
    } catch {
      // Response body is not JSON, use status message
    }
    throw new Error(errorMessage);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

export interface LLMConfig {
  enabled: boolean;
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  timeout: number;
  system_prompt?: string;  // v0.40
}

export const api = {
  wiki: {
    status: () => request<WikiStatus>('/wiki/status'),
    search: (query: string, limit = 10) =>
      request<SearchResult[]>(`/wiki/search?q=${encodeURIComponent(query)}&limit=${limit}`),
    readPage: (pageName: string) =>
      request<WikiPage>(`/wiki/page/${encodeURIComponent(pageName)}`),
    writePage: (pageName: string, content: string) =>
      request<{ ok: boolean }>(`/wiki/page`, {
        method: 'POST',
        body: JSON.stringify({ page_name: pageName, content }),
      }),
    sinkStatus: () => request<SinkStatus>('/wiki/sink/status'),
    lint: (wikiId?: string) =>
      request<{ issues: unknown[] }>(wikiId ? `/wiki/${wikiId}/lint` : '/wiki/lint'),
    recommend: (wikiId?: string) =>
      request<unknown[]>(wikiId ? `/wiki/${wikiId}/recommend` : '/wiki/recommend'),
    suggestSynthesis: (wikiId?: string) =>
      request<unknown[]>(wikiId ? `/wiki/${wikiId}/suggest_synthesis` : '/wiki/suggest_synthesis'),
    graphAnalyze: (wikiId?: string) =>
      request<unknown>(wikiId ? `/wiki/${wikiId}/graph_analyze` : '/wiki/graph_analyze'),
    graph: (params: { currentPage?: string; mode?: string; wikiId?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.currentPage) q.set('current_page', params.currentPage);
      if (params.mode) q.set('mode', params.mode);
      if (params.wikiId) q.set('wiki_id', params.wikiId);
      const qs = q.toString();
      return request<GraphData>(params.wikiId ? `/wiki/${params.wikiId}/graph${qs ? `?${qs}` : ''}` : `/wiki/graph${qs ? `?${qs}` : ''}`);
    },
    scoped: {
      readPage: (wikiId: string, pageName: string) =>
        request<WikiPage>(`/wiki/${wikiId}/page/${encodeURIComponent(pageName)}`),
      writePage: (wikiId: string, pageName: string, content: string) =>
        request<{ ok: boolean }>(`/wiki/${wikiId}/page`, {
          method: 'POST',
          body: JSON.stringify({ page_name: pageName, content }),
        }),
      search: (wikiId: string, query: string, limit = 10) =>
        request<SearchResult[]>(`/wiki/${wikiId}/search?q=${encodeURIComponent(query)}&limit=${limit}`),
      status: (wikiId: string) => request<WikiStatus>(`/wiki/${wikiId}/status`),
      sinkStatus: (wikiId: string) => request<SinkStatus>(`/wiki/${wikiId}/sink/status`),
      pages: (wikiId: string) => request<Array<{ name: string; path: string }>>(`/wiki/${wikiId}/pages`),
    },
  },

  search: {
    cross: (query: string, limit = 10, wikis?: string[]) =>
      request<SearchResult[]>(`/search/cross?q=${encodeURIComponent(query)}&limit=${limit}${wikis ? `&wikis=${wikis.join(',')}` : ''}`),
  },

  wikis: {
    list: () => request<{ wikis: Array<Record<string, unknown>>; default_wiki_id: string | null }>('/wikis'),
    get: (wikiId: string) => request<Record<string, unknown>>(`/wikis/${wikiId}`),
    register: (data: Record<string, unknown>) =>
      request<{ wiki_id: string }>('/wikis', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (wikiId: string, data: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/wikis/${wikiId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    unregister: (wikiId: string) =>
      request<{ ok: boolean }>(`/wikis/${wikiId}`, { method: 'DELETE' }),
    reload: (wikiId: string) =>
      request<{ ok: boolean }>(`/wikis/${wikiId}/reload`, { method: 'POST' }),
    health: (wikiId: string) =>
      request<Record<string, unknown>>(`/wikis/${wikiId}/health`),
    scan: (path?: string) =>
      request<{ wikis: unknown[] }>('/wikis/scan', {
        method: 'POST',
        body: JSON.stringify({ scan_paths: path ? [path] : undefined }),
      }),
  },

  agent: {
    status: (wikiId?: string) =>
      request<{
        state: string;
        scheduler_tasks: TaskInfo[];
        pending_work: unknown;
        action_log: unknown[];
        pending_confirmations: number;
        dream_proposals: Record<string, number>;
        unread_notifications: number;
      }>(`/agent/status${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    tools: (wikiId?: string) => request<Array<{ name: string; description: string }>>(`/agent/tools${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    sessions: () => request<{ sessions: unknown[] }>('/agent/sessions'),
    createSession: (wikiId?: string) =>
      request<{ session_id: string }>('/agent/sessions', {
        method: 'POST',
        body: JSON.stringify({ wiki_id: wikiId }),
      }),
    getSession: (sessionId: string) =>
      request<Record<string, unknown>>(`/agent/sessions/${sessionId}`),
    deleteSession: (sessionId: string) =>
      request<{ deleted: boolean }>(`/agent/sessions/${sessionId}`, { method: 'DELETE' }),
    getSessionMessages: (sessionId: string, limit = 50, before?: string) =>
      request<{ messages: unknown[]; session_id: string }>(
        `/agent/sessions/${sessionId}/messages?limit=${limit}${before ? `&before=${before}` : ''}`
      ),
    getConfig: () => request<LLMConfig>('/agent/config'),
    saveConfig: (cfg: LLMConfig) =>
      request<{ saved: boolean }>('/agent/config', {
        method: 'PUT',
        body: JSON.stringify(cfg),
      }),
    reloadConfig: () =>
      request<{ reloaded: boolean }>('/agent/config/reload', { method: 'POST' }),
    // v0.40: session revert, edit, abort, status
    revertSession: (sessionId: string, messageId: string) =>
      request<{ reverted: number; session_id: string }>(
        `/agent/sessions/${sessionId}/revert`,
        { method: 'POST', body: JSON.stringify({ message_id: messageId }) }
      ),
    editMessage: (sessionId: string, messageId: string, content: string) =>
      request<{ updated: boolean; message_id: string }>(
        `/agent/sessions/${sessionId}/messages/${messageId}`,
        { method: 'PUT', body: JSON.stringify({ content }) }
      ),
    abortSession: (sessionId: string) =>
      request<{ aborted: boolean; session_id: string }>(
        `/agent/sessions/${sessionId}/abort`,
        { method: 'POST' }
      ),
    getSessionStatus: (sessionId: string) =>
      request<{ session_id: string; status: string }>(
        `/agent/sessions/${sessionId}/status`
      ),
  },

  dream: {
    log: (limit = 20, wikiId?: string) => request<DreamEdit[]>(`/agent/dream/log?limit=${limit}${wikiId ? `&wiki_id=${wikiId}` : ''}`),
    run: (wikiId?: string) => request<Record<string, unknown>>(`/agent/dream/run${wikiId ? `?wiki_id=${wikiId}` : ''}`, { method: 'POST' }),
    proposals: (wikiId?: string) => request<{ proposals: Record<string, DreamProposal[]>; stats: Record<string, number> }>(`/agent/dream/proposals${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    approve: (id: string) => request<DreamProposal>(`/agent/dream/proposals/${id}/approve`, { method: 'POST' }),
    reject: (id: string) => request<DreamProposal>(`/agent/dream/proposals/${id}/reject`, { method: 'POST' }),
    batchApprove: (ids: string[]) => request<{ approved: number; results: DreamProposal[] }>('/agent/dream/proposals/batch-approve', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
    apply: (ids?: string[], wikiId?: string) => request<{ applied: number; errors: unknown[] }>(`/agent/dream/proposals/apply${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ ids: ids || null }),
    }),
  },

  notifications: {
    list: (wikiId?: string) => request<Notification[]>(`/agent/notifications${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    markRead: (id: string) =>
      request<void>(`/agent/notifications/${id}/read`, { method: 'POST' }),
  },

  confirmations: {
    list: (wikiId?: string) => request<Record<string, Confirmation[]>>(`/agent/confirmations${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    approve: (id: string, wikiId?: string, arguments_?: Record<string, unknown>, response: 'once' | 'always' = 'once') => request<Record<string, unknown>>(`/agent/confirmations/${id}${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ arguments: arguments_, response }),
    }),
    reject: (id: string, wikiId?: string) => request<Record<string, unknown>>(`/agent/confirmations/${id}${wikiId ? `?wiki_id=${wikiId}` : ''}`, { method: 'DELETE' }),
    batchApprove: (ids: string[], wikiId?: string) => request<Record<string, unknown>[]>(`/agent/confirmations/batch${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
    approveAndContinue: (id: string, sessionId: string, wikiId?: string, signal?: AbortSignal): ReadableStream<ChatStreamEvent> => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`;
      return new ReadableStream<ChatStreamEvent>({
        async start(controller) {
          try {
            const res = await fetch(`${API_BASE}/agent/confirmations/${id}/approve-and-continue${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
              method: 'POST',
              headers,
              body: JSON.stringify({ session_id: sessionId, wiki_id: wikiId }),
              signal,
            });
            if (!res.ok || !res.body) {
              controller.enqueue({ type: 'error', message: `HTTP ${res.status}` });
              controller.close();
              return;
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
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
                      const event = JSON.parse(data) as ChatStreamEvent;
                      controller.enqueue(event);
                    } catch { /* ignore parse errors */ }
                  }
                }
              }
            }
          } catch (e) {
            // Phase 5.1 (v0.36): abort errors are expected.
            if (e instanceof DOMException && e.name === 'AbortError') {
              controller.close();
              return;
            }
            controller.enqueue({ type: 'error', message: String(e) });
          } finally {
            controller.close();
          }
        },
      });
    },
  },

  ingest: {
    log: (limit = 20, wikiId?: string) => request<IngestLogEntry[]>(`/agent/ingest/log?limit=${limit}${wikiId ? `&wiki_id=${wikiId}` : ''}`),
    changes: (id: string) => request<IngestLogEntry>(`/agent/ingest/log/${id}`),
    revert: (id: string) => request<Record<string, unknown>>(`/agent/ingest/log/${id}/revert`, { method: 'POST' }),
  },
};