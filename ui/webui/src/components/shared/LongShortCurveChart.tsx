/**
 * LongShortCurveChart — long-short pair NAV curve.
 *
 * Single line chart showing the long-short portfolio net value over time,
 * with a horizontal reference line at NAV=1.0.
 *
 * Usage:
 *   <LongShortCurveChart curve={[{ date: '2024-01-01', value: 1.0 }, ...]} />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface CurvePoint {
  date: string;
  value: number;
}

interface LongShortCurveChartProps {
  curve: CurvePoint[];
  height?: number;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function LongShortCurveChart({ curve, height = 200, className }: LongShortCurveChartProps) {
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
    if (!svgRef.current || width === 0 || curve.length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 12, right: 24, bottom: 28, left: 48 };
    const w = width - margin.left - margin.right;
    const h = height - margin.top - margin.bottom;

    const g = svg
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Parse data
    const data = curve.map((d) => ({
      date: new Date(d.date),
      value: d.value,
    }));

    // Scales
    const x = d3.scaleTime()
      .domain(d3.extent(data, (d) => d.date) as [Date, Date])
      .range([0, w]);

    const yExtent = d3.extent(data, (d) => d.value) as [number, number];
    const yPad = (yExtent[1] - yExtent[0]) * 0.1 || 0.05;
    const y = d3.scaleLinear()
      .domain([yExtent[0] - yPad, yExtent[1] + yPad])
      .range([h, 0]);

    // Axes
    g.append('g')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(5).tickSize(0).tickPadding(8))
      .call((g) => g.select('.domain').remove())
      .selectAll('text')
      .style('font-size', '10px')
      .style('fill', 'var(--muted-foreground)');

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(8).tickFormat(d3.format('.2f')))
      .call((g) => g.select('.domain').remove())
      .selectAll('text')
      .style('font-size', '10px')
      .style('fill', 'var(--muted-foreground)');

    // Reference line at y=1.0
    if (1.0 >= y.domain()[0] && 1.0 <= y.domain()[1]) {
      g.append('line')
        .attr('x1', 0)
        .attr('x2', w)
        .attr('y1', y(1.0))
        .attr('y2', y(1.0))
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-width', 0.5)
        .attr('stroke-dasharray', '4,4')
        .attr('opacity', 0.5);
    }

    // NAV curve
    const line = d3.line<{ date: Date; value: number }>()
      .x((d) => x(d.date))
      .y((d) => y(d.value))
      .curve(d3.curveMonotoneX);

    // Gradient fill below curve
    const defs = svg.append('defs');
    const gradient = defs.append('linearGradient')
      .attr('id', 'ls-gradient')
      .attr('x1', '0').attr('y1', '0')
      .attr('x2', '0').attr('y2', '1');
    gradient.append('stop')
      .attr('offset', '0%')
      .attr('stop-color', 'var(--chart-1)')
      .attr('stop-opacity', 0.15);
    gradient.append('stop')
      .attr('offset', '100%')
      .attr('stop-color', 'var(--chart-1)')
      .attr('stop-opacity', 0.02);

    // Area for gradient
    const area = d3.area<{ date: Date; value: number }>()
      .x((d) => x(d.date))
      .y0(h)
      .y1((d) => y(d.value))
      .curve(d3.curveMonotoneX);

    g.append('path')
      .datum(data)
      .attr('fill', 'url(#ls-gradient)')
      .attr('d', area);

    // Main line with entrance animation
    const path = g.append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', 'var(--chart-1)')
      .attr('stroke-width', 2)
      .attr('d', line);

    const totalLength = path.node()!.getTotalLength();
    path
      .attr('stroke-dasharray', `${totalLength} ${totalLength}`)
      .attr('stroke-dashoffset', totalLength)
      .transition()
      .duration(600)
      .ease(d3.easeCubicInOut)
      .attr('stroke-dashoffset', 0);

    // Start and end dots
    g.append('circle')
      .attr('cx', x(data[0].date))
      .attr('cy', y(data[0].value))
      .attr('r', 3)
      .attr('fill', 'var(--chart-1)');

    g.append('circle')
      .attr('cx', x(data[data.length - 1].date))
      .attr('cy', y(data[data.length - 1].value))
      .attr('r', 3)
      .attr('fill', 'var(--chart-1)');

    // End value label
    g.append('text')
      .attr('x', x(data[data.length - 1].date) + 6)
      .attr('y', y(data[data.length - 1].value) + 3)
      .style('font-size', '10px')
      .style('fill', 'var(--chart-1)')
      .style('font-weight', '600')
      .text(data[data.length - 1].value.toFixed(2));

  }, [curve, width, height]);

  useEffect(() => {
    renderChart();
  }, [renderChart]);

  if (curve.length === 0) {
    return (
      <div className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}>
        暂无数据
      </div>
    );
  }

  return (
    <div ref={containerRef} className={cn('w-full', className)}>
      <svg ref={svgRef} className="w-full" />
    </div>
  );
}
