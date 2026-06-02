/**
 * PPT Generator - API client for backend endpoints
 */

const API_BASE = '/api/ppt';

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
  const response = await fetch(`${API_BASE}/outline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, num_slides: numSlides, language }),
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to generate outline');
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
  const response = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ outline, theme, language }),
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to generate presentation');
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
  const response = await fetch(`${API_BASE}/from-research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ research_id: researchId, theme, language }),
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to generate from research');
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
  const response = await fetch(`${API_BASE}/from-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_session_id: chatSessionId, theme, language }),
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to generate from chat');
  }
  
  return response.json();
}

/**
 * Get list of available themes
 */
export async function getThemes(): Promise<ThemesResponse> {
  const response = await fetch(`${API_BASE}/themes`);
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to get themes');
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
