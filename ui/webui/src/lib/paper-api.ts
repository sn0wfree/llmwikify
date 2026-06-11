/**
 * Paper - API client for /api/paper/* endpoints.
 *
 * v0.4.0 paper UI enhancement. Mirrors reproduction-api.ts structure.
 *
 * Endpoints:
 *   POST /api/paper/start       — kick off async extraction, return session_id
 *   GET  /api/paper/list        — list all paper sessions
 *   GET  /api/paper/list-raw    — list *.pdf files in <project>/raw/
 *   POST /api/paper/upload      — multipart upload, save to ~/.llmwikify/papers/
 *   GET  /api/paper/{sid}/status — session + events + artifacts (polled)
 *
 * Backend emits these event_types during the 5-phase pipeline:
 *   1. extract.started   → pending → extracting
 *   2. extract.llm_called / extract.llm_done
 *   3. wiki.building     → wiki_building
 *   4. wiki.written
 *   5. finalize.done     → done
 *   err: error           → error
 */

const API_BASE = '/api/paper';
const POLL_INTERVAL_MS = 2000;

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

function authHeaders(): Record<string, string> {
  const token = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_TOKEN;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    let msg = `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(text);
      msg = parsed.error || parsed.detail || msg;
    } catch { /* keep status */ }
    throw new Error(msg);
  }
  return res.json();
}

// ─── Types ─────────────────────────────────────────────────────

export type PaperStatus =
  | 'pending'
  | 'extracting'
  | 'analyzing'
  | 'done'
  | 'error';

export interface PaperSession {
  id: string;
  wiki_id: string;
  paper_id: string;
  source_type: 'pdf' | 'url' | 'raw';
  source_ref: string;
  symbol: string;
  start_date: string;
  end_date: string;
  status: PaperStatus;
  error: string | null;
  strategy_signal_type: string;
  strategy_params_json: string;
  created_at: string;
  updated_at: string;
}

export interface PaperEvent {
  id: number;
  session_id: string;
  event_type: string;
  payload_json: string;
  created_at: string;
}

export interface PaperArtifact {
  id: string;
  session_id: string;
  kind: string;
  wiki_page: string;
  meta_json: string;
  created_at: string;
}

export interface RawFile {
  filename: string;
  path: string;
  size_bytes: number;
  mtime: string;
}

export interface PaperStatusResponse {
  session: PaperSession;
  events: PaperEvent[];
  artifacts: PaperArtifact[];
}

export interface PaperStartRequest {
  paper_id: string;
  source_type: 'pdf' | 'url' | 'raw';
  source_ref: string;
  paper_content?: string;
  wiki_id?: string;
  symbol?: string;
  start_date?: string;
  end_date?: string;
}

export interface PaperStartResponse {
  session_id: string;
  status: PaperStatus;
  paper_id: string;
}

export interface PaperListResponse {
  sessions: PaperSession[];
}

export interface PaperListRawResponse {
  files: RawFile[];
  raw_dir: string | null;
}

export interface PaperUploadResponse {
  paper_id: string;
  path: string;
  size_bytes: number;
  filename: string;
}

// ─── Public API ──────────────────────────────────────────────

/** Kick off async paper extraction. Returns immediately with session_id. */
export async function startPaper(req: PaperStartRequest): Promise<PaperStartResponse> {
  return fetchJson<PaperStartResponse>(`${API_BASE}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
}

/** Get full session + events + artifacts (used for polling). */
export async function getPaperStatus(sessionId: string): Promise<PaperStatusResponse> {
  return fetchJson<PaperStatusResponse>(`${API_BASE}/${sessionId}/status`, {
    headers: { ...authHeaders() },
  });
}

/** List all paper sessions (source_type=pdf|url|raw). */
export async function listPaperSessions(): Promise<PaperListResponse> {
  return fetchJson<PaperListResponse>(`${API_BASE}/list`, {
    headers: { ...authHeaders() },
  });
}

/** List *.pdf files in <project>/raw/. */
export async function listRawPapers(): Promise<PaperListRawResponse> {
  return fetchJson<PaperListRawResponse>(`${API_BASE}/list-raw`, {
    headers: { ...authHeaders() },
  });
}

/** Delete a paper session. */
export async function deletePaperSession(sessionId: string): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(`${API_BASE}/${sessionId}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  });
}

/** Upload a PDF file. Saves to ~/.llmwikify/papers/{safe(paper_id)}.pdf. */
export async function uploadPaperFile(
  paperId: string,
  file: File,
): Promise<PaperUploadResponse> {
  const form = new FormData();
  form.append('paper_id', paperId);
  form.append('file', file);
  return fetchJson<PaperUploadResponse>(`${API_BASE}/upload`, {
    method: 'POST',
    body: form,
    ...authHeaders(),
  });
}

// ─── Helpers ──────────────────────────────────────────────────

export const PAPER_FIVE_PHASES = [
  { key: 'extract',      label: 'LLM 提取', num: 1, desc: '调用 LLM 解析论文结构' },
  { key: 'wiki_building', label: '构建页面', num: 2, desc: '生成 Source/Factor/Strategy 页' },
  { key: 'wiki_written',  label: '写入 Wiki', num: 3, desc: 'wiki.write_page × N' },
  { key: 'backtest',      label: '自动回测', num: 4, desc: '因子 IC + 策略回测' },
  { key: 'finalize',      label: '归档',     num: 5, desc: '标记完成' },
] as const;

export const PAPER_STATUS_LABELS: Record<PaperStatus, { icon: string; color: string; text: string }> = {
  pending:      { icon: '◌', color: 'text-muted-foreground',  text: '待启动' },
  extracting:   { icon: '↓', color: 'text-primary',          text: 'LLM 提取中' },
  analyzing:    { icon: '◐', color: 'text-primary',          text: '构建+回测中' },
  done:         { icon: '✓', color: 'text-green-400',        text: '已完成' },
  error:        { icon: '✗', color: 'text-red-400',          text: '失败' },
};

/** Map a backend event_type to the front-end phase it represents. */
export function paperEventToPhase(eventType: string): typeof PAPER_FIVE_PHASES[number]['key'] | null {
  if (eventType === 'extract.started' || eventType === 'extract.llm_called' || eventType === 'extract.llm_done') return 'extract';
  if (eventType === 'wiki.written') return 'wiki_written';
  if (eventType === 'backtest.started' || eventType === 'backtest.done') return 'backtest';
  if (eventType === 'finalize.done') return 'finalize';
  return null;
}

export { POLL_INTERVAL_MS, sleep };
