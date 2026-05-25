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

export const api = {
  // Wiki management (multi-wiki)
  wikis: {
    list: () => request<{ wikis: Array<Record<string, unknown>>; default_wiki_id: string | null }>('/wikis'),
    get: (wikiId: string) => request<Record<string, unknown>>(`/wikis/${wikiId}`),
    register: (data: Record<string, unknown>) =>
      request<Record<string, unknown>>('/wikis', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (wikiId: string, data: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/wikis/${wikiId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    unregister: (wikiId: string) =>
      request<void>(`/wikis/${wikiId}`, { method: 'DELETE' }),
    reload: (wikiId: string) =>
      request<Record<string, unknown>>(`/wikis/${wikiId}/reload`, { method: 'POST' }),
    health: (wikiId: string) => request<Record<string, unknown>>(`/wikis/${wikiId}/health`),
    scan: (scanPaths?: string[], scanDepth?: number) =>
      request<{ new_wikis: Array<Record<string, unknown>>; count: number }>('/wikis/scan', {
        method: 'POST',
        body: JSON.stringify({ scan_paths: scanPaths, scan_depth: scanDepth }),
      }),
  },

  // Cross-wiki search
  search: {
    cross: (query: string, limit = 10, wikis?: string[]) =>
      request<{ results: Array<Record<string, unknown>>; total_results: number; searched_wikis: string[] }>(
        `/search/cross?q=${encodeURIComponent(query)}&limit=${limit}${wikis ? `&wikis=${wikis.join(',')}` : ''}`
      ),
  },

  // Wiki-scoped operations (backward compatible)
  wiki: {
    // Legacy endpoints (use default wiki)
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
    suggestSynthesis: (sourceName?: string) =>
      request<Record<string, unknown>>(`/wiki/suggest_synthesis${sourceName ? `?source_name=${encodeURIComponent(sourceName)}` : ''}`),
    graphAnalyze: () => request<Record<string, unknown>>('/wiki/graph_analyze'),
    graph: (currentPage?: string, mode?: string) =>
      request<GraphData>(`/wiki/graph${currentPage ? `?current_page=${encodeURIComponent(currentPage)}${mode ? `&mode=${mode}` : ''}` : mode ? `?mode=${mode}` : ''}`),

    // Wiki-scoped endpoints (for multi-wiki mode)
    scoped: {
      status: (wikiId: string) => request<WikiStatus>(`/wiki/${wikiId}/status`),
      sinkStatus: (wikiId: string) => request<SinkStatus>(`/wiki/${wikiId}/sink/status`),
      pages: (wikiId: string) =>
        request<{ pages: string[]; count: number }>(`/wiki/${wikiId}/pages`),
      search: (wikiId: string, query: string, limit = 10) =>
        request<SearchResult[]>(`/wiki/${wikiId}/search?q=${encodeURIComponent(query)}&limit=${limit}`),
      readPage: (wikiId: string, pageName: string) =>
        request<WikiPage>(`/wiki/${wikiId}/page/${encodeURIComponent(pageName)}`),
      writePage: (wikiId: string, pageName: string, content: string) =>
        request<{ message: string; confirmation_id?: string; status?: string }>(
          `/wiki/${wikiId}/page`,
          { method: 'POST', body: JSON.stringify({ page_name: pageName, content }) }
        ),
      lint: (wikiId: string) => request<Record<string, unknown>>(`/wiki/${wikiId}/lint`),
      recommend: (wikiId: string) => request<Array<Record<string, unknown>>>(`/wiki/${wikiId}/recommend`),
      graph: (wikiId: string, currentPage?: string, mode?: string) =>
        request<GraphData>(`/wiki/${wikiId}/graph${currentPage ? `?current_page=${encodeURIComponent(currentPage)}${mode ? `&mode=${mode}` : ''}` : mode ? `?mode=${mode}` : ''}`),
    },
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
