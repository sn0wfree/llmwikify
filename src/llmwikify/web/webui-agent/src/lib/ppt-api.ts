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

export interface ThemeColors {
  primary: string;
  secondary: string;
  background: string;
  text: string;
  accent: string;
}

export interface Theme {
  name: string;
  label: string;
  colors: ThemeColors;
}

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
 * Generate content based on outline (Step 2)
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

export default {
  generateOutline,
  generatePresentation,
  generateFromResearch,
  generateFromChat,
  getThemes,
};
