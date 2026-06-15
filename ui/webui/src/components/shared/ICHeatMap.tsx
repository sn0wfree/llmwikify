/**
 * ICHeatMap — monthly IC heatmap for factor analysis.
 *
 * Computes average IC per year×month from ic_series, renders as a
 * colored grid using the shared HeatMap component.
 *
 * Usage:
 *   <ICHeatMap icSeries={[{ date: '2024-01-15', ic: 0.05 }, ...]} />
 */

import { useMemo } from 'react';
import { HeatMap } from './HeatMap';

// ─── Types ──────────────────────────────────────────────────

interface ICPoint {
  date: string;
  ic: number;
}

interface ICHeatMapProps {
  icSeries: ICPoint[];
  height?: number;
  className?: string;
}

// ─── Constants ──────────────────────────────────────────────

const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月',
  '7月', '8月', '9月', '10月', '11月', '12月'];

// ─── Component ──────────────────────────────────────────────

export function ICHeatMap({ icSeries, height = 140, className }: ICHeatMapProps) {
  const { rows, cols, data } = useMemo(() => {
    if (!icSeries || icSeries.length === 0) {
      return { rows: [], cols: MONTH_LABELS, data: {} };
    }

    // Group IC values by year-month
    const monthly: Record<string, number[]> = {};
    for (const pt of icSeries) {
      const d = new Date(pt.date);
      if (isNaN(d.getTime())) continue;
      const year = d.getFullYear();
      const month = d.getMonth(); // 0-indexed
      const key = `${year}-${month}`;
      if (!monthly[key]) monthly[key] = [];
      monthly[key].push(pt.ic);
    }

    // Compute average per year-month
    const yearMonthAvg: Record<string, Record<number, number>> = {};
    for (const [key, values] of Object.entries(monthly)) {
      const [yearStr, monthStr] = key.split('-');
      const year = parseInt(yearStr, 10);
      const month = parseInt(monthStr, 10);
      if (!yearMonthAvg[year]) yearMonthAvg[year] = {};
      yearMonthAvg[year][month] = values.reduce((a, b) => a + b, 0) / values.length;
    }

    const years = Object.keys(yearMonthAvg).sort();
    const data: Record<string, Record<number, number>> = {};
    for (const year of years) {
      data[year] = yearMonthAvg[year];
    }

    return { rows: years, cols: MONTH_LABELS, data };
  }, [icSeries]);

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}>
        暂无 IC 数据
      </div>
    );
  }

  return (
    <div className={className}>
      <HeatMap
        rows={rows}
        cols={cols}
        data={data}
        height={height}
        format={(v) => v === 0 ? '—' : v.toFixed(3)}
      />
    </div>
  );
}
