const API_BASE = '/api';
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

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
  score: number;
  has_sink?: boolean;
  sink_entries?: number;
}

export interface WikiStatus {
  page_count: number;
  sink_entries: number;
  db_path: string;
  is_initialized: boolean;
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

export const api = {
  wiki: {
    status: () => request<WikiStatus>('/wiki/status'),
    search: (query: string, limit = 10) =>
      request<SearchResult[]>(`/wiki/search?q=${encodeURIComponent(query)}&limit=${limit}`),
    readPage: (pageName: string) =>
      request<WikiPage>(`/wiki/page/${encodeURIComponent(pageName)}`),
    writePage: (pageName: string, content: string) =>
      request<{ message: string; confirmation_id?: string; status?: string }>(
        '/wiki/page',
        { method: 'POST', body: JSON.stringify({ page_name: pageName, content }) }
      ),
    sinkStatus: () => request<SinkStatus>('/wiki/sink/status'),
    lint: () => request<Record<string, unknown>>('/wiki/lint'),
    recommend: () => request<Array<Record<string, unknown>>>('/wiki/recommend'),
  },

  agent: {
    chat: (message: string) =>
      request<{ response: string; actions: unknown[] }>('/agent/chat', {
        method: 'POST',
        body: JSON.stringify({ message }),
      }),
    status: () =>
      request<{
        state: string;
        scheduler_tasks: TaskInfo[];
        pending_work: unknown;
        action_log: unknown[];
        pending_confirmations: number;
        dream_proposals: Record<string, number>;
        unread_notifications: number;
      }>('/agent/status'),
    tools: () => request<Array<{ name: string; description: string }>>('/agent/tools'),
  },

  dream: {
    log: (limit = 20) => request<DreamEdit[]>(`/agent/dream/log?limit=${limit}`),
    run: () => request<Record<string, unknown>>('/agent/dream/run', { method: 'POST' }),
    proposals: () => request<{ proposals: Record<string, DreamProposal[]>; stats: Record<string, number> }>('/agent/dream/proposals'),
    approve: (id: string) => request<DreamProposal>(`/agent/dream/proposals/${id}/approve`, { method: 'POST' }),
    reject: (id: string) => request<DreamProposal>(`/agent/dream/proposals/${id}/reject`, { method: 'POST' }),
    batchApprove: (ids: string[]) => request<{ approved: number; results: DreamProposal[] }>('/agent/dream/proposals/batch-approve', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
    apply: (ids?: string[]) => request<{ applied: number; errors: unknown[] }>('/agent/dream/proposals/apply', {
      method: 'POST',
      body: JSON.stringify({ ids: ids || null }),
    }),
  },

  notifications: {
    list: () => request<Notification[]>('/agent/notifications'),
    markRead: (id: string) =>
      request<void>(`/agent/notifications/${id}/read`, { method: 'POST' }),
  },

  confirmations: {
    list: () => request<Record<string, Confirmation[]>>('/agent/confirmations'),
    approve: (id: string) => request<Record<string, unknown>>(`/agent/confirmations/${id}`, { method: 'POST' }),
    reject: (id: string) => request<Record<string, unknown>>(`/agent/confirmations/${id}`, { method: 'DELETE' }),
    batchApprove: (ids: string[]) => request<Record<string, unknown>[]>('/agent/confirmations/batch', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  },

  ingest: {
    log: (limit = 20) => request<IngestLogEntry[]>(`/agent/ingest/log?limit=${limit}`),
    changes: (id: string) => request<IngestLogEntry>(`/agent/ingest/log/${id}`),
    revert: (id: string) => request<Record<string, unknown>>(`/agent/ingest/log/${id}/revert`, { method: 'POST' }),
  },
};
