/**
 * StrategySelector — select a Strategy page from wiki/strategy/ directory.
 *
 * Fetches strategy list from /api/strategy/list and displays as selectable cards.
 *
 * Usage:
 *   <StrategySelector onSelect={(slug) => setSelectedStrategy(slug)} />
 */

import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { TrendingUp, Check } from 'lucide-react';

// ─── Types ──────────────────────────────────────────────────

interface StrategyItem {
  _slug: string;
  title?: string;
  strategy_class?: string;
  signal_type?: string;
  status?: string;
}

interface StrategySelectorProps {
  onSelect: (slug: string) => void;
  selectedSlug?: string;
  className?: string;
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'text-muted-foreground',
  backtested: 'text-primary',
  validated: 'text-success',
  deprecated: 'text-destructive',
};

// ─── Component ──────────────────────────────────────────────

export function StrategySelector({ onSelect, selectedSlug, className }: StrategySelectorProps) {
  const [strategies, setStrategies] = useState<StrategyItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchStrategies = async () => {
      try {
        const res = await fetch('/api/strategy/list');
        const data = await res.json();
        if (!cancelled) {
          setStrategies(data.strategies || []);
        }
      } catch {
        if (!cancelled) {
          setStrategies([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    fetchStrategies();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className={cn('text-sm text-muted-foreground p-3', className)}>
        Loading strategies...
      </div>
    );
  }

  if (strategies.length === 0) {
    return (
      <div className={cn('text-sm text-muted-foreground p-3 text-center', className)}>
        <TrendingUp className="w-4 h-4 mx-auto mb-1 opacity-50" />
        <div>No strategies found</div>
        <div className="text-[10px] mt-1 opacity-70">
          Create one via Paper extraction or manually in wiki/strategy/
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-1', className)}>
      {strategies.map((s) => {
        const isSelected = selectedSlug === s._slug;
        return (
          <button
            key={s._slug}
            onClick={() => onSelect(s._slug)}
            className={cn(
              'w-full text-left px-3 py-2 rounded-lg text-sm transition-colors',
              isSelected
                ? 'bg-primary/12 text-foreground'
                : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <TrendingUp className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate font-medium">
                  {s.title || s._slug}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {s.signal_type && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                    {s.signal_type}
                  </span>
                )}
                {s.status && (
                  <span className={cn('text-[10px]', STATUS_COLORS[s.status] || 'text-muted-foreground')}>
                    {s.status}
                  </span>
                )}
                {isSelected && <Check className="w-3.5 h-3.5 text-primary" />}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}