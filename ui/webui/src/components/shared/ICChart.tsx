/**
 * ICChart — IC time series + distribution histogram.
 *
 * Two-panel chart for factor analysis:
 *   Top: IC time series line with zero line
 *   Bottom: IC distribution histogram with mean/median markers
 *
 * Usage:
 *   <ICChart icSeries={[{ date: '2024-01-01', ic: 0.05 }, ...]} />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface ICPoint {
  date: Date | string | number;
  ic: number;
}

interface ICChartProps {
  icSeries: ICPoint[];
  height?: number;
  className?: string;
}

// ─── Component ──────────────────────────────────────────────

export function ICChart({ icSeries, height = 300, className }: ICChartProps) {
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
    if (!svgRef.current || width === 0 || icSeries.length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const margin = { top: 16, right: 24, bottom: 12, left: 48 };
    const histHeight = 100;
    const histMargin = { top: 8, bottom: 28, left: 48, right: 24 };
    const gap = 24;

    const tsW = width - margin.left - margin.right;
    const tsH = (height - gap - histHeight - histMargin.top - histMargin.bottom) / 2;
    const histW = width - histMargin.left - histMargin.right;

    // Parse data
    const parsed = icSeries.map((d) => ({
      date: d.date instanceof Date ? d.date : new Date(d.date),
      ic: d.ic,
    })).sort((a, b) => +a.date - +b.date);

    const icValues = parsed.map((d) => d.ic);
    const icMean = d3.mean(icValues) || 0;
    const icStd = d3.deviation(icValues) || 1;

    // ── Top: IC Time Series ──
    const x = d3.scaleTime()
      .domain(d3.extent(parsed, (d) => d.date) as [Date, Date])
      .range([0, tsW]);

    const yExtent = d3.extent(icValues) as [number, number];
    const yPad = Math.max(Math.abs(yExtent[0]), Math.abs(yExtent[1])) * 0.1 || 0.01;
    const y = d3.scaleLinear()
      .domain([Math.min(yExtent[0] - yPad, -yPad), Math.max(yExtent[1] + yPad, yPad)])
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

    // Zero line
    if (y.domain()[0] < 0 && y.domain()[1] > 0) {
      g.append('line')
        .attr('x1', 0).attr('x2', tsW)
        .attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-opacity', 0.5)
        .attr('stroke-dasharray', '4 4');
    }

    // Mean line
    g.append('line')
      .attr('x1', 0).attr('x2', tsW)
      .attr('y1', y(icMean)).attr('y2', y(icMean))
      .attr('stroke', 'var(--chart-4)')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '6 3');

    // IC bars (positive = green, negative = red)
    const barW = Math.max(1, tsW / parsed.length - 1);
    g.selectAll('rect')
      .data(parsed)
      .join('rect')
      .attr('x', (d) => x(d.date) - barW / 2)
      .attr('y', (d) => d.ic >= 0 ? y(d.ic) : y(0))
      .attr('width', barW)
      .attr('height', (d) => Math.abs(y(0) - y(d.ic)))
      .attr('fill', (d) => d.ic >= 0 ? 'var(--success)' : 'var(--destructive)')
      .attr('opacity', 0.7)
      .attr('rx', 1);

    // Axes
    g.append('g').attr('transform', `translate(0,${tsH})`)
      .call(d3.axisBottom(x).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    // Label
    g.append('text')
      .attr('x', tsW).attr('y', y(icMean) - 6)
      .attr('text-anchor', 'end')
      .attr('fill', 'var(--chart-4)')
      .attr('font-size', '9px')
      .text(`mean=${icMean.toFixed(4)}`);

    // ── Bottom: IC Distribution Histogram ──
    const hg = svg.append('g')
      .attr('transform', `translate(${histMargin.left},${margin.top + tsH + gap})`);

    // X scale for histogram
    const xHist = d3.scaleLinear()
      .domain([(d3.min(icValues) ?? 0) * 1.1, (d3.max(icValues) ?? 0) * 1.1])
      .range([0, histW]);

    // Histogram bins
    const bins = d3.bin()
      .domain(xHist.domain() as [number, number])
      .thresholds(20)(icValues);

    const yHist = d3.scaleLinear()
      .domain([0, d3.max(bins, (b) => b.length) || 1])
      .range([histHeight, 0]);

    // Bars
    hg.selectAll('rect')
      .data(bins)
      .join('rect')
      .attr('x', (d) => xHist(d.x0 || 0) + 1)
      .attr('y', (d) => yHist(d.length))
      .attr('width', (d) => Math.max(0, xHist(d.x1 || 0) - xHist(d.x0 || 0) - 2))
      .attr('height', (d) => histHeight - yHist(d.length))
      .attr('fill', (d) => {
        const mid = ((d.x0 || 0) + (d.x1 || 0)) / 2;
        return mid >= 0 ? 'var(--success)' : 'var(--destructive)';
      })
      .attr('opacity', 0.6)
      .attr('rx', 1);

    // Mean marker
    hg.append('line')
      .attr('x1', xHist(icMean)).attr('x2', xHist(icMean))
      .attr('y1', 0).attr('y2', histHeight)
      .attr('stroke', 'var(--chart-4)')
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', '4 2');

    // Zero marker
    if (xHist.domain()[0] < 0 && xHist.domain()[1] > 0) {
      hg.append('line')
        .attr('x1', xHist(0)).attr('x2', xHist(0))
        .attr('y1', 0).attr('y2', histHeight)
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3 2');
    }

    // Axes
    hg.append('g').attr('transform', `translate(0,${histHeight})`)
      .call(d3.axisBottom(xHist).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    hg.append('g')
      .call(d3.axisLeft(yHist).ticks(4).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '9px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));
  }, [icSeries, width, height]);

  useEffect(() => { renderChart(); }, [renderChart]);

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}