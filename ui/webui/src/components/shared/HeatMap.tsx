/**
 * HeatMap — d3-based heatmap for monthly returns / IC distribution.
 *
 * Renders a grid of colored cells. Positive values green, negative red.
 * Uses d3 for scale/color computation, renders as SVG.
 *
 * Usage:
 *   <HeatMap
 *     rows={['2023', '2024']}
 *     cols={['Jan', 'Feb', ..., 'Dec']}
 *     data={{ '2023': { 0: 1.2, 1: -0.5, ... }, ... }}
 *     format={(v) => `${v.toFixed(1)}%`}
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface HeatMapProps {
  rows: string[];
  cols: string[];
  data: Record<string, Record<number, number>>;
  format?: (v: number) => string;
  height?: number;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function HeatMap({
  rows,
  cols,
  data,
  format = (v) => v.toFixed(1),
  height = 200,
  className,
}: HeatMapProps) {
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
    if (!svgRef.current || width === 0 || rows.length === 0 || cols.length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 4, right: 4, bottom: 4, left: 40 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const cellW = innerW / cols.length;
    const cellH = innerH / rows.length;

    // Color scale: diverging red-green
    const allValues = rows.flatMap((r) => cols.map((_, ci) => data[r]?.[ci] ?? 0));
    const maxAbs = Math.max(d3.max(allValues.map(Math.abs)) || 1, 0.1);
    const colorScale = d3.scaleLinear<string>()
      .domain([-maxAbs, 0, maxAbs])
      .range(['#ef4444', 'var(--card)', '#10b981'])
      .interpolate(d3.interpolateRgb);

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Row labels
    rows.forEach((row, ri) => {
      g.append('text')
        .attr('x', margin.left - 8)
        .attr('y', ri * cellH + cellH / 2)
        .attr('text-anchor', 'end')
        .attr('dominant-baseline', 'middle')
        .attr('fill', 'var(--muted-foreground)')
        .attr('font-size', '10px')
        .text(row);
    });

    // Cells
    rows.forEach((row, ri) => {
      cols.forEach((_, ci) => {
        const value = data[row]?.[ci] ?? 0;
        const cell = g.append('rect')
          .attr('x', ci * cellW)
          .attr('y', ri * cellH)
          .attr('width', cellW - 1)
          .attr('height', cellH - 1)
          .attr('rx', 2)
          .attr('fill', colorScale(value))
          .attr('opacity', 0.85);

        // Tooltip on hover
        cell.append('title').text(`${row} ${cols[ci]}: ${format(value)}`);

        // Value text
        g.append('text')
          .attr('x', ci * cellW + cellW / 2 - 0.5)
          .attr('y', ri * cellH + cellH / 2)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('fill', Math.abs(value) > maxAbs * 0.5 ? 'white' : 'var(--foreground)')
          .attr('font-size', '9px')
          .attr('font-weight', '500')
          .attr('pointer-events', 'none')
          .text(format(value));
      });
    });
  }, [rows, cols, data, width, height, format]);

  useEffect(() => { renderChart(); }, [renderChart]);

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}