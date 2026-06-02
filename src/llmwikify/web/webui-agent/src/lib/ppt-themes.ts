/**
 * PPT Generator - Frontend theme configuration
 */

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

export const THEMES: Theme[] = [
  {
    name: 'professional',
    label: 'Professional',
    colors: {
      primary: '#1a73e8',
      secondary: '#5f6368',
      background: '#ffffff',
      text: '#202124',
      accent: '#ea4335',
    },
  },
  {
    name: 'modern',
    label: 'Modern',
    colors: {
      primary: '#6366f1',
      secondary: '#8b5cf6',
      background: '#0f172a',
      text: '#f8fafc',
      accent: '#06b6d4',
    },
  },
  {
    name: 'minimal',
    label: 'Minimal',
    colors: {
      primary: '#18181b',
      secondary: '#71717a',
      background: '#ffffff',
      text: '#18181b',
      accent: '#a1a1aa',
    },
  },
  {
    name: 'nature',
    label: 'Nature',
    colors: {
      primary: '#16a34a',
      secondary: '#22c55e',
      background: '#f0fdf4',
      text: '#14532d',
      accent: '#86efac',
    },
  },
  {
    name: 'warm',
    label: 'Warm',
    colors: {
      primary: '#ea580c',
      secondary: '#f97316',
      background: '#fff7ed',
      text: '#7c2d12',
      accent: '#fdba74',
    },
  },
  {
    name: 'dark',
    label: 'Dark',
    colors: {
      primary: '#3b82f6',
      secondary: '#60a5fa',
      background: '#111827',
      text: '#f9fafb',
      accent: '#fbbf24',
    },
  },
  {
    name: 'academic',
    label: 'Academic',
    colors: {
      primary: '#1e3a5f',
      secondary: '#2563eb',
      background: '#f8fafc',
      text: '#1e293b',
      accent: '#dc2626',
    },
  },
  {
    name: 'creative',
    label: 'Creative',
    colors: {
      primary: '#d946ef',
      secondary: '#a855f7',
      background: '#fdf4ff',
      text: '#701a75',
      accent: '#f472b6',
    },
  },
];

export function getTheme(name: string): Theme {
  return THEMES.find((t) => t.name === name) || THEMES[0];
}
