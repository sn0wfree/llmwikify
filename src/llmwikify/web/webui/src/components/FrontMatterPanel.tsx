import { useState } from 'react';

export interface FrontMatterData {
  title?: string;
  type?: string;
  created?: string;
  authors?: string | string[];
  year?: string | number;
  venue?: string;
  tags?: string | string[];
  [key: string]: unknown;
}

interface FrontMatterPanelProps {
  metadata: FrontMatterData;
}

const FIELD_LABELS: Record<string, { label: string; icon: string }> = {
  title: { label: 'Title', icon: '📄' },
  type: { label: 'Type', icon: '📂' },
  created: { label: 'Created', icon: '📅' },
  authors: { label: 'Authors', icon: '👤' },
  year: { label: 'Year', icon: '📆' },
  venue: { label: 'Venue', icon: '🏛️' },
  tags: { label: 'Tags', icon: '🏷️' },
};

const DISPLAY_ORDER = ['title', 'type', 'created', 'authors', 'year', 'venue', 'tags'];

function formatValue(key: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value.join(', ');
  }
  return String(value ?? '');
}

export function FrontMatterPanel({ metadata }: FrontMatterPanelProps) {
  const [collapsed, setCollapsed] = useState(true);

  const entries = DISPLAY_ORDER
    .filter((key) => metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== '')
    .map((key) => [key, metadata[key]] as [string, unknown]);

  if (entries.length === 0) {
    return null;
  }

  const title = metadata.title ? String(metadata.title) : 'Metadata';

  return (
    <div className="border-b border-slate-700 bg-slate-800/50">
      {/* Collapsed header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-slate-400">{collapsed ? '▶' : '▼'}</span>
          <span className="font-medium">Metadata</span>
          <span className="text-slate-500">: {title}</span>
        </div>
        <span className="text-xs text-slate-500">{entries.length} fields</span>
      </button>

      {/* Expanded content */}
      {!collapsed && (
        <div className="px-4 pb-3 space-y-2">
          {entries.map(([key, value]) => {
            const { label, icon } = FIELD_LABELS[key] || { label: key, icon: '📋' };
            return (
              <div key={key} className="flex items-start gap-2 text-sm">
                <span className="text-slate-400 w-5 text-center shrink-0">{icon}</span>
                <span className="text-slate-400 w-16 shrink-0">{label}:</span>
                <span className="text-slate-200">
                  {key === 'tags' && Array.isArray(value) ? (
                    <span className="flex flex-wrap gap-1">
                      {value.map((tag, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded"
                        >
                          {tag}
                        </span>
                      ))}
                    </span>
                  ) : (
                    formatValue(key, value)
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
