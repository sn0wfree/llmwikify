/**
 * DrawdownChart — underwater equity curve.
 *
 * Displays drawdown as a filled area chart below zero.
 * Optionally annotates top-N drawdown periods.
 *
 * Usage:
 *   <DrawdownChart
 *     data={[{ date: '2024-01-01', drawdown: -0.05 }, ...]}
 *     topN={3}
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface DrawdownPoint {
  date: Date | string | number;
  drawdown: number;  // negative value (e.g. -0.05 = -5%)
}

interface DrawdownChartProps {
  data: DrawdownPoint[];
  height?: number;
  topN?: number;
  format?: (v: number) => string;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function DrawdownChart({
  data,
  height = 200,
  topN = 3,
  format = (v) => `${(v * 100).toFixed(2)}%`,
  className,
}: DrawdownChartProps) {
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
    if (!svgRef.current || width === 0 || data.length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 16, right: 24, bottom: 28, left: 56 };
    const innerW = Math.max(0, width - margin.left - margin.right);
    const innerH = height - margin.top - margin.bottom;

    // Parse data
    const parsed = data.map((d) => ({
      date: d.date instanceof Date ? d.date : new Date(d.date),
      drawdown: d.drawdown,
    })).sort((a, b) => +a.date - +b.date);

    const xExtent = d3.extent(parsed, (d) => d.date) as [Date, Date];
    const yMin = d3.min(parsed, (d) => d.drawdown) || -0.1;

    // Scales
    const x = d3.scaleTime().domain(xExtent).range([0, innerW]).nice();
    const y = d3.scaleLinear()
      .domain([yMin * 1.15, 0.01])
      .range([innerH, 0])
      .nice();

    // Main group
    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Grid
    g.append('g').selectAll('line')
      .data(y.ticks(5))
      .join('line')
      .attr('x1', 0).attr('x2', innerW)
      .attr('y1', (d) => y(d)).attr('y2', (d) => y(d))
      .attr('stroke', 'var(--border)')
      .attr('stroke-opacity', 0.3)
      .attr('stroke-dasharray', '2 3');

    // Zero line
    g.append('line')
      .attr('x1', 0).attr('x2', innerW)
      .attr('y1', y(0)).attr('y2', y(0))
      .attr('stroke', 'var(--muted-foreground)')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', 1);

    // Area fill
    const areaGen = d3.area<{ date: Date; drawdown: number }>()
      .x((d) => x(d.date))
      .y0(y(0))
      .y1((d) => y(d.drawdown))
      .curve(d3.curveMonotoneX);

    g.append('path').datum(parsed)
      .attr('fill', 'var(--destructive)')
      .attr('fill-opacity', 0.3)
      .attr('d', areaGen);

    // Line stroke
    const lineGen = d3.line<{ date: Date; drawdown: number }>()
      .x((d) => x(d.date))
      .y((d) => y(d.drawdown))
      .curve(d3.curveMonotoneX);

    g.append('path').datum(parsed)
      .attr('fill', 'none')
      .attr('stroke', 'var(--destructive)')
      .attr('stroke-width', 1.5)
      .attr('d', lineGen);

    // Find top-N drawdown troughs
    if (topN > 0) {
      // Simple: pick the N most negative points
      const sorted = [...parsed].sort((a, b) => a.drawdown - b.drawdown);
      const topPoints = sorted.slice(0, topN);

      topPoints.forEach((pt, i) => {
        const cx = x(pt.date);
        const cy = y(pt.drawdown);

        // Marker circle
        g.append('circle')
          .attr('cx', cx)
          .attr('cy', cy)
          .attr('r', 3)
          .attr('fill', 'var(--destructive)')
          .attr('stroke', 'var(--background)')
          .attr('stroke-width', 1.5);

        // Label
        g.append('text')
          .attr('x', cx)
          .attr('y', cy - 8)
          .attr('text-anchor', 'middle')
          .attr('fill', 'var(--destructive)')
          .attr('font-size', '9px')
          .attr('font-weight', '500')
          .text(format(pt.drawdown));
      });
    }

    // Axes
    g.append('g').attr('transform', `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickFormat((d) => format(d as number)).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));
  }, [data, width, height, topN, format]);

  useEffect(() => { renderChart(); }, [renderChart]);

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}