const API_BASE = '/api';
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

export type ChatStreamEvent =
  | { type: 'session_created'; session_id: string }
  | { type: 'message_delta'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call_start'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_call_end'; tool: string; result: unknown }
  | { type: 'tool_call_error'; tool: string; error: string }
  | { type: 'done'; final_response: string; actions: unknown[] }
  | { type: 'confirmation_required'; confirmation_id: string; details: Record<string, unknown> };

export type ResearchStreamEvent =
  | { type: 'step'; step: string; message: string; session_id?: string }
  | { type: 'reasoning'; action: string; round: number; phase: string }
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
  | { type: 'review_passed'; round: number; score: number; feedback: string }
  | { type: 'review_issues'; round: number; score: number; issues: string[] }
  | { type: 'review_max_rounds'; message: string }
  | { type: 'done'; report: ResearchReport }
  | { type: 'error'; error: string };

export interface ResearchReport {
  query: string;
  markdown: string;
  sources: Array<{ id: string; title: string; url: string; source_type: string }>;
  synthesis_summary?: Record<string, number>;
  rounds?: number;
  quality_score?: number;
}

export interface ResearchSession {
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
  sub_queries?: ResearchSubQuery[];
  sources?: ResearchSource[];
  sub_query_count?: number;
  source_count?: number;
}

export interface ResearchSubQuery {
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

export interface ResearchSource {
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

export function chatStream(
  message: string,
  sessionId?: string,
  wikiId?: string
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
          body: JSON.stringify({ message, session_id: sessionId, wiki_id: wikiId }),
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
}

export const api = {
  wikis: {
    list: () => request<{ wikis: Array<Record<string, unknown>>; default_wiki_id: string | null }>('/wikis'),
    get: (wikiId: string) => request<Record<string, unknown>>(`/wikis/${wikiId}`),
  },

  wiki: {
    status: () => request<WikiStatus>('/wiki/status'),
    search: (query: string, limit = 10) =>
      request<SearchResult[]>(`/wiki/search?q=${encodeURIComponent(query)}&limit=${limit}`),
    readPage: (pageName: string) =>
      request<WikiPage>(`/wiki/page/${encodeURIComponent(pageName)}`),
    sinkStatus: () => request<SinkStatus>('/wiki/sink/status'),
    scoped: {
      readPage: (wikiId: string, pageName: string) =>
        request<WikiPage>(`/wiki/${wikiId}/page/${encodeURIComponent(pageName)}`),
    },
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
    approve: (id: string, wikiId?: string) => request<Record<string, unknown>>(`/agent/confirmations/${id}${wikiId ? `?wiki_id=${wikiId}` : ''}`, { method: 'POST' }),
    reject: (id: string, wikiId?: string) => request<Record<string, unknown>>(`/agent/confirmations/${id}${wikiId ? `?wiki_id=${wikiId}` : ''}`, { method: 'DELETE' }),
    batchApprove: (ids: string[], wikiId?: string) => request<Record<string, unknown>[]>(`/agent/confirmations/batch${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
    approveAndContinue: (id: string, sessionId: string, wikiId?: string): ReadableStream<ChatStreamEvent> => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`;
      return new ReadableStream<ChatStreamEvent>({
        async start(controller) {
          try {
            const res = await fetch(`${API_BASE}/agent/confirmations/${id}/approve-and-continue${wikiId ? `?wiki_id=${wikiId}` : ''}`, {
              method: 'POST',
              headers,
              body: JSON.stringify({ session_id: sessionId, wiki_id: wikiId }),
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

  research: {
    start: (query: string, wikiId?: string): ReadableStream<ResearchStreamEvent> => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`;
      return new ReadableStream<ResearchStreamEvent>({
        async start(controller) {
          try {
            const res = await fetch(`${API_BASE}/research/start`, {
              method: 'POST',
              headers,
              body: JSON.stringify({ query, wiki_id: wikiId }),
            });
            if (!res.ok || !res.body) {
              controller.enqueue({ type: 'error', error: `HTTP ${res.status}` });
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
                if (line.startsWith('data: ')) {
                  try {
                    const event = JSON.parse(line.slice(6)) as ResearchStreamEvent;
                    controller.enqueue(event);
                  } catch { /* skip malformed */ }
                }
              }
            }
          } catch (e) {
            controller.enqueue({ type: 'error', error: String(e) });
          } finally {
            controller.close();
          }
        },
      });
    },
    list: (wikiId?: string) => request<{ research_sessions: ResearchSession[] }>(`/research/${wikiId ? `?wiki_id=${wikiId}` : ''}`),
    get: (id: string) => request<ResearchSession>(`/research/${id}`),
    pause: (id: string) => request<{ paused: boolean }>(`/research/${id}/pause`, { method: 'POST' }),
    resume: (id: string): ReadableStream<ResearchStreamEvent> => {
      const headers: Record<string, string> = {};
      if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`;
      return new ReadableStream<ResearchStreamEvent>({
        async start(controller) {
          try {
            const res = await fetch(`${API_BASE}/research/${id}/resume`, { method: 'POST', headers });
            if (!res.ok || !res.body) {
              controller.enqueue({ type: 'error', error: `HTTP ${res.status}` });
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
                if (line.startsWith('data: ')) {
                  try {
                    const event = JSON.parse(line.slice(6)) as ResearchStreamEvent;
                    controller.enqueue(event);
                  } catch { /* skip malformed */ }
                }
              }
            }
          } catch (e) {
            controller.enqueue({ type: 'error', error: String(e) });
          } finally {
            controller.close();
          }
        },
      });
    },
    delete: (id: string) => request<{ cancelled: boolean }>(`/research/${id}`, { method: 'DELETE' }),
    sources: (id: string) => request<{ sources: ResearchSource[] }>(`/research/${id}/sources`),
    subQueries: (id: string) => request<{ sub_queries: ResearchSubQuery[] }>(`/research/${id}/sub-queries`),
    rate: (id: string, rating: number, sourceRatings?: Record<string, number>, feedback?: string) =>
      request<{ rated: boolean }>(`/research/${id}/rate`, {
        method: 'POST',
        body: JSON.stringify({ rating, source_ratings: sourceRatings, feedback }),
      }),
  },
};