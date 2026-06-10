/**
 * MetricCards — horizontal metric card group.
 *
 * Displays a row of KPI cards with icon, label, and value.
 * Used for Factor IC/IR cards and Strategy KPI top bar.
 *
 * Usage:
 *   <MetricCards metrics={[
 *     { label: 'Sharpe', value: '1.85', icon: BarChart3, color: 'text-success' },
 *   ]} />
 */

import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

// ─── Types ──────────────────────────────────────────────────

export interface Metric {
  label: string;
  value: string;
  icon?: LucideIcon;
  color?: string;
  bg?: string;
}

interface MetricCardsProps {
  metrics: Metric[];
  columns?: number;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function MetricCards({
  metrics,
  columns = 6,
  className,
}: MetricCardsProps) {
  const gridCols = {
    2: 'grid-cols-2',
    3: 'grid-cols-3',
    4: 'grid-cols-4',
    5: 'grid-cols-5',
    6: 'grid-cols-6',
  }[columns] || 'grid-cols-6';

  return (
    <div className={cn('grid gap-3', gridCols, className)}>
      {metrics.map(({ label, value, icon: Icon, color, bg }) => (
        <div
          key={label}
          className="bg-card border border-border rounded-lg p-3 transition-all hover:border-primary/30"
        >
          <div className="flex items-start justify-between mb-2">
            <div className="text-[11px] text-muted-foreground">{label}</div>
            {Icon && (
              <div className={cn('w-7 h-7 rounded-md flex items-center justify-center', bg || 'bg-muted')}>
                <Icon className={cn('w-3.5 h-3.5', color || 'text-muted-foreground')} />
              </div>
            )}
          </div>
          <div className={cn('text-xl font-semibold tabular-nums', color || 'text-foreground')}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}