/**
 * PPT Generator - API client for backend endpoints
 */

const API_BASE = '/api/ppt';

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
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: reqBody,
    });
  } catch (e) {
    reportFetchError(endpoint, e, 'POST');
    throw e;
  }

  if (!response.ok) {
    const text = await response.text();
    reportApiError(response, text, 'POST', reqBody);
    let error: { error?: string };
    try { error = JSON.parse(text); } catch { error = {}; }
    throw new Error(error.error || `Failed to generate outline (${response.status})`);
  }

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
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: reqBody,
    });
  } catch (e) {
    reportFetchError(endpoint, e, 'POST');
    throw e;
  }

  if (!response.ok) {
    const text = await response.text();
    reportApiError(response, text, 'POST', reqBody);
    let error: { error?: string };
    try { error = JSON.parse(text); } catch { error = {}; }
    throw new Error(error.error || `Failed to generate presentation (${response.status})`);
  }

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
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: reqBody,
    });
  } catch (e) {
    reportFetchError(endpoint, e, 'POST');
    throw e;
  }

  if (!response.ok) {
    const text = await response.text();
    reportApiError(response, text, 'POST', reqBody);
    let error: { error?: string };
    try { error = JSON.parse(text); } catch { error = {}; }
    throw new Error(error.error || `Failed to generate from research (${response.status})`);
  }

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
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: reqBody,
    });
  } catch (e) {
    reportFetchError(endpoint, e, 'POST');
    throw e;
  }

  if (!response.ok) {
    const text = await response.text();
    reportApiError(response, text, 'POST', reqBody);
    let error: { error?: string };
    try { error = JSON.parse(text); } catch { error = {}; }
    throw new Error(error.error || `Failed to generate from chat (${response.status})`);
  }

  return response.json();
}

/**
 * Get list of available themes
 */
export async function getThemes(): Promise<ThemesResponse> {
  const endpoint = `${API_BASE}/themes`;
  let response: Response;
  try {
    response = await fetch(endpoint);
  } catch (e) {
    reportFetchError(endpoint, e, 'GET');
    throw e;
  }

  if (!response.ok) {
    const text = await response.text();
    reportApiError(response, text, 'GET');
    let error: { error?: string };
    try { error = JSON.parse(text); } catch { error = {}; }
    throw new Error(error.error || `Failed to get themes (${response.status})`);
  }

  return response.json();
}

export default {
  generateOutline,
  generatePresentation,
  generateFromResearch,
  generateFromChat,
  getThemes,
};
