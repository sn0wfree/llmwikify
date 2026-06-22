/**
 * FactorSelector — select a Factor definition from quant/factors/ library.
 *
 * Fetches factor list from /api/factor/library/list and flattens the
 * categories dict into a single array of selectable cards.
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
  validated: 'text-emerald-500',
  deprecated: 'text-rose-500',
};

const CLASS_COLOR: Record<string, string> = {
  momentum: 'bg-blue-500',
  volatility: 'bg-purple-500',
  value: 'bg-emerald-500',
  quality: 'bg-amber-500',
  size: 'bg-cyan-500',
  growth: 'bg-pink-500',
  signal_composite: 'bg-violet-500',
  ma_cross: 'bg-indigo-500',
  rsi: 'bg-orange-500',
};

// ─── Component ──────────────────────────────────────────────

export function FactorSelector({ onSelect, selectedSlug, className }: FactorSelectorProps) {
  const [factors, setFactors] = useState<FactorItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchFactors = async () => {
      try {
        const res = await fetch('/api/factor/library/list');
        const data = await res.json();
        if (!cancelled) {
          // Backend returns {"categories": {price: [...], fundamental: [...], ...}}
          // Flatten into a single array and rename _name to _slug for the UI contract.
          const flat = Object.values(data.categories || {}).flat() as any[];
          const items: FactorItem[] = flat.map((f) => ({
            _slug: f._name ?? f._path ?? '',
            title: f.name_cn || f.name,
            factor_class: f.factor_class ?? f.subcategory ?? f.category,
            factor_params: f.factor_params ?? f.default_params,
            status: f.status,
          }));
          setFactors(items);
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
          Create one via Paper extraction or manually in quant/factors/
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-1', className)}>
      {factors.map((f) => {
        const isSelected = selectedSlug === f._slug;
        const colorBar = f.factor_class ? CLASS_COLOR[f.factor_class] || 'bg-muted-foreground' : 'bg-muted-foreground';
        return (
          <button
            key={f._slug}
            onClick={() => onSelect(f._slug)}
            className={cn(
              'relative w-full text-left pl-3 pr-2.5 py-2 rounded-md text-sm transition-all',
              isSelected
                ? 'bg-primary/10 text-foreground border-l-2 border-primary'
                : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground border-l-2 border-transparent',
            )}
          >
            {!isSelected && (
              <span className={cn('absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full', colorBar)} />
            )}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <Beaker className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate font-medium">
                  {f.title || f._slug}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {f.factor_class && (
                  <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                    {f.factor_class}
                  </span>
                )}
                {f.status && (
                  <span className={cn('text-[9px] font-medium', STATUS_COLORS[f.status] || 'text-muted-foreground')}>
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