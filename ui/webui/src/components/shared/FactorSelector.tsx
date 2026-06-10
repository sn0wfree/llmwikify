/**
 * FactorSelector — select a Factor page from wiki/factor/ directory.
 *
 * Fetches factor list from /api/factor/list and displays as selectable cards.
 *
 * Usage:
 *   <FactorSelector onSelect={(slug) => setSelectedFactor(slug)} />
 */

import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { Beaker, Check } from 'lucide-react';

// ─── Types ──────────────────────────────────────────────────

interface FactorItem {
  _slug: string;
  title?: string;
  factor_class?: string;
  factor_params?: Record<string, unknown>;
  status?: string;
}

interface FactorSelectorProps {
  onSelect: (slug: string) => void;
  selectedSlug?: string;
  className?: string;
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'text-muted-foreground',
  validated: 'text-success',
  deprecated: 'text-destructive',
};

// ─── Component ──────────────────────────────────────────────

export function FactorSelector({ onSelect, selectedSlug, className }: FactorSelectorProps) {
  const [factors, setFactors] = useState<FactorItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchFactors = async () => {
      try {
        const res = await fetch('/api/factor/list');
        const data = await res.json();
        if (!cancelled) {
          setFactors(data.factors || []);
        }
      } catch {
        if (!cancelled) {
          setFactors([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    fetchFactors();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className={cn('text-sm text-muted-foreground p-3', className)}>
        Loading factors...
      </div>
    );
  }

  if (factors.length === 0) {
    return (
      <div className={cn('text-sm text-muted-foreground p-3 text-center', className)}>
        <Beaker className="w-4 h-4 mx-auto mb-1 opacity-50" />
        <div>No factors found</div>
        <div className="text-[10px] mt-1 opacity-70">
          Create one via Paper extraction or manually in wiki/factor/
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-1', className)}>
      {factors.map((f) => {
        const isSelected = selectedSlug === f._slug;
        return (
          <button
            key={f._slug}
            onClick={() => onSelect(f._slug)}
            className={cn(
              'w-full text-left px-3 py-2 rounded-lg text-sm transition-colors',
              isSelected
                ? 'bg-primary/12 text-foreground'
                : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Beaker className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate font-medium">
                  {f.title || f._slug}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {f.factor_class && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                    {f.factor_class}
                  </span>
                )}
                {f.status && (
                  <span className={cn('text-[10px]', STATUS_COLORS[f.status] || 'text-muted-foreground')}>
                    {f.status}
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