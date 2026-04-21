const API_BASE = '/api';

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

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
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
      request<{ message: string }>('/wiki/page', {
        method: 'POST',
        body: JSON.stringify({ page_name: pageName, content }),
      }),
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
      }>('/agent/status'),
    tools: () => request<Array<{ name: string; description: string }>>('/agent/tools'),
  },

  dream: {
    log: (limit = 20) => request<DreamEdit[]>(`/agent/dream/log?limit=${limit}`),
    run: () => request<Record<string, unknown>>('/agent/dream/run', { method: 'POST' }),
  },

  notifications: {
    list: () => request<Notification[]>('/agent/notifications'),
    markRead: (id: string) =>
      request<void>(`/agent/notifications/${id}/read`, { method: 'POST' }),
  },
};
