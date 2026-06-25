/**
 * GroupNavChart — multi-line time series chart for quantile group cumulative NAV.
 *
 * Renders G1→GN cumulative NAV curves. Monotonic G1 > GN = good factor discrimination.
 *
 * Usage:
 *   <GroupNavChart
 *     series={{
 *       G1: [{ date: 20200131, nav: 1.0 }, ...],
 *       G2: [{ date: 20200131, nav: 0.98 }, ...],
 *     }}
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface NAVPoint {
  date: number; // YYYYMMDD int or ms timestamp
  nav: number;
}

interface GroupNavChartProps {
  series: Record<string, NAVPoint[]>;
  height?: number;
  className?: string;
}

// ─── Constants ──────────────────────────────────────────────

const GROUP_COLORS: Record<string, string> = {
  G1: 'var(--chart-1)',
  G2: 'var(--chart-2)',
  G3: 'var(--chart-3)',
  G4: 'var(--chart-4)',
  G5: 'var(--chart-5)',
};

// ─── Helpers ────────────────────────────────────────────────

function parseNAVDate(d: number): Date {
  // If > 10 digits, treat as ms timestamp; otherwise YYYYMMDD
  if (d > 1e12) return new Date(d);
  const s = String(d);
  return new Date(
    Number(s.slice(0, 4)),
    Number(s.slice(4, 6)) - 1,
    Number(s.slice(6, 8)),
  );
}

// ─── Component ──────────────────────────────────────────────

export function GroupNavChart({ series, height = 300, className }: GroupNavChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);

  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        setWidth(containerRef.current.getBoundingClientRect().width);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const renderChart = useCallback(() => {
    if (!svgRef.current || width === 0 || Object.keys(series).length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 8, right: 24, bottom: 28, left: 48 };
    const tsW = width - margin.left - margin.right;
    const tsH = height - margin.top - margin.bottom;

    // Parse all series
    const parsed: Record<string, { date: Date; nav: number }[]> = {};
    const allDates: Date[] = [];
    const allVals: number[] = [];
    for (const [group, pts] of Object.entries(series)) {
      parsed[group] = pts
        .map((p) => ({ date: parseNAVDate(p.date), nav: p.nav }))
        .sort((a, b) => +a.date - +b.date);
      allDates.push(...parsed[group].map((p) => p.date));
      allVals.push(...parsed[group].map((p) => p.nav));
    }

    if (allDates.length === 0) return;

    const x = d3.scaleTime()
      .domain(d3.extent(allDates) as [Date, Date])
      .range([0, tsW]);

    const yExtent = d3.extent(allVals) as [number, number];
    const yPad = (yExtent[1] - yExtent[0]) * 0.1 || 0.05;
    const y = d3.scaleLinear()
      .domain([yExtent[0] - yPad, yExtent[1] + yPad])
      .range([tsH, 0]);

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Grid
    g.append('g').selectAll('line')
      .data(y.ticks(5))
      .join('line')
      .attr('x1', 0).attr('x2', tsW)
      .attr('y1', (d) => y(d)).attr('y2', (d) => y(d))
      .attr('stroke', 'var(--border)')
      .attr('stroke-opacity', 0.3)
      .attr('stroke-dasharray', '2 3');

    // 1.0 reference line
    if (y.domain()[0] < 1.0 && y.domain()[1] > 1.0) {
      g.append('line')
        .attr('x1', 0).attr('x2', tsW)
        .attr('y1', y(1.0)).attr('y2', y(1.0))
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-opacity', 0.5)
        .attr('stroke-dasharray', '4 4');
    }

    // Lines
    const lineGen = d3.line<{ date: Date; nav: number }>()
      .x((d) => x(d.date))
      .y((d) => y(d.nav))
      .defined((d) => !isNaN(d.nav) && isFinite(d.nav));

    const sortedGroups = Object.keys(parsed).sort((a, b) => {
      const na = parseInt(a.replace(/\D/g, ''), 10) || 0;
      const nb = parseInt(b.replace(/\D/g, ''), 10) || 0;
      return na - nb;
    });

    for (const group of sortedGroups) {
      const pts = parsed[group];
      const color = GROUP_COLORS[group] || `var(--chart-${(sortedGroups.indexOf(group) % 5) + 1})`;

      g.append('path')
        .datum(pts)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1.5)
        .attr('d', lineGen);
    }

    // Axes
    g.append('g').attr('transform', `translate(0,${tsH})`)
      .call(d3.axisBottom(x).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickFormat((d) => typeof d === 'number' ? d.toFixed(2) : String(d)).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    // Legend
    const legend = g.append('g')
      .attr('transform', `translate(${tsW - sortedGroups.length * 56 - 4}, -4)`);
    sortedGroups.forEach((group, i) => {
      const color = GROUP_COLORS[group] || `var(--chart-${(i % 5) + 1})`;
      const lg = legend.append('g').attr('transform', `translate(${i * 56}, 0)`);
      lg.append('line')
        .attr('x1', 0).attr('x2', 12)
        .attr('y1', 0).attr('y2', 0)
        .attr('stroke', color)
        .attr('stroke-width', 2);
      lg.append('text')
        .attr('x', 15).attr('y', 0)
        .attr('dominant-baseline', 'middle')
        .attr('fill', color)
        .attr('font-size', '9px')
        .attr('font-weight', '600')
        .text(group);
    });
  }, [series, width, height]);

  useEffect(() => { renderChart(); }, [renderChart]);

  if (Object.keys(series).length === 0) {
    return (
      <div className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}>
        暂无数据
      </div>
    );
  }

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}
