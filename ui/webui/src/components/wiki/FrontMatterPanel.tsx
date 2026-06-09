import { useState } from 'react';
import {
  ChevronDown, FileText, Folder, Calendar, User, Hash,
  Building2, Tag, FileCode, Braces,
} from 'lucide-react';
import { cn } from '@/lib/utils';

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

const FIELD_ICONS: Record<string, typeof FileText> = {
  title: FileText,
  type: Folder,
  created: Calendar,
  authors: User,
  year: Hash,
  venue: Building2,
  tags: Tag,
};

const DISPLAY_ORDER = ['title', 'type', 'created', 'authors', 'year', 'venue', 'tags'];

function formatValue(key: string, value: unknown): string {
  if (Array.isArray(value)) return value.join(', ');
  return String(value ?? '');
}

export function FrontMatterPanel({ metadata }: FrontMatterPanelProps) {
  const [collapsed, setCollapsed] = useState(true);

  const entries = DISPLAY_ORDER
    .filter((key) => metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== '')
    .map((key) => [key, metadata[key]] as [string, unknown]);

  if (entries.length === 0) return null;

  const title = metadata.title ? String(metadata.title) : 'Metadata';

  return (
    <div className="border-b border-border/50 glass" style={{ background: 'color-mix(in srgb, var(--card) 40%, transparent)' }}>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-2 text-sm text-foreground/85 hover:bg-white/[0.04] transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <ChevronDown
            className={cn(
              'w-3.5 h-3.5 text-muted-foreground transition-transform duration-200 shrink-0',
              collapsed && '-rotate-90',
            )}
          />
          <Braces className="w-3.5 h-3.5 text-primary shrink-0" />
          <span className="font-medium">Front Matter</span>
          <span className="text-muted-foreground truncate">: {title}</span>
        </div>
        <span className="text-[10px] text-muted-foreground font-mono tabular-nums shrink-0">
          {entries.length} field{entries.length === 1 ? '' : 's'}
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 pt-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 animate-slide-up">
          {entries.map(([key, value]) => {
            const Icon = FIELD_ICONS[key] || FileCode;
            return (
              <div
                key={key}
                className="flex items-start gap-2 text-xs p-2 rounded-md bg-white/[0.03] border border-border/30"
              >
                <Icon className="w-3 h-3 text-muted-foreground mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 font-semibold">
                    {key}
                  </div>
                  {key === 'tags' && Array.isArray(value) ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {value.map((tag, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 text-[10px] font-medium bg-primary/15 text-primary rounded"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="text-foreground/90 mt-0.5 break-words">
                      {formatValue(key, value)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
