/**
 * LineChart — d3 line/area chart component.
 *
 * Follows GraphView.tsx patterns: containerRef + svgRef + resize listener.
 * Uses CSS variables for chart colors (--chart-1 to --chart-5).
 *
 * Usage:
 *   <LineChart
 *     series={[{ id: 'equity', label: 'Equity', data: [...] }]}
 *     height={280}
 *     showArea
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

export interface SeriesPoint {
  date: Date | string | number;
  value: number;
}

export interface Series {
  id: string;
  label?: string;
  data: SeriesPoint[];
  color?: string;
}

interface LineChartProps {
  series: Series[];
  height?: number;
  yFormat?: (n: number) => string;
  showArea?: boolean;
  showGrid?: boolean;
  showDots?: boolean;
  zeroLine?: boolean;
  className?: string;
}

// ─── Constants ──────────────────────────────────────────────

const CHART_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
];

const MARGIN = { top: 16, right: 24, bottom: 28, left: 56 };

// ─── Component ──────────────────────────────────────────────

export function LineChart({
  series,
  height = 280,
  yFormat = (n) => n.toLocaleString(),
  showArea = true,
  showGrid = true,
  showDots = false,
  zeroLine = false,
  className,
}: LineChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);

  // Resize listener (matches GraphView.tsx pattern)
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

  // Main render callback
  const renderChart = useCallback(() => {
    if (!svgRef.current || width === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
    const innerH = height - MARGIN.top - MARGIN.bottom;

    // Flatten all points
    const allPoints = series.flatMap((s) =>
      s.data.map((d) => ({
        date: d.date instanceof Date ? d.date : new Date(d.date),
        value: d.value,
      })),
    );
    if (allPoints.length === 0) return;

    const xExtent = d3.extent(allPoints, (d) => d.date) as [Date, Date];
    const [yMin, yMax] = d3.extent(allPoints, (d) => d.value) as [number, number];
    const yPad = (yMax - yMin) * 0.08 || 1;

    // Scales
    const x = d3.scaleTime().domain(xExtent).range([0, innerW]).nice();
    const y = d3.scaleLinear()
      .domain([yMin - yPad, yMax + yPad])
      .range([innerH, 0])
      .nice();

    // Main group
    const g = svg.append('g')
      .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);

    // Grid lines
    if (showGrid) {
      g.append('g').attr('class', 'grid')
        .selectAll('line')
        .data(y.ticks(5))
        .join('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', (d) => y(d)).attr('y2', (d) => y(d))
        .attr('stroke', 'var(--border)')
        .attr('stroke-opacity', 0.3)
        .attr('stroke-dasharray', '2 3');
    }

    // X axis
    g.append('g').attr('transform', `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    // Y axis
    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickFormat((d) => yFormat(Number(d))).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    // Zero line
    if (zeroLine && yMin < 0 && yMax > 0) {
      g.append('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-opacity', 0.4)
        .attr('stroke-dasharray', '4 4');
    }

    // Generators
    const lineGen = d3.line<{ date: Date; value: number }>()
      .x((d) => x(d.date))
      .y((d) => y(d.value))
      .curve(d3.curveMonotoneX);

    const areaGen = d3.area<{ date: Date; value: number }>()
      .x((d) => x(d.date))
      .y0(showArea && yMin < 0 ? y(0) : innerH)
      .y1((d) => y(d.value))
      .curve(d3.curveMonotoneX);

    // Draw each series
    series.forEach((s, i) => {
      const color = s.color ?? CHART_COLORS[i % CHART_COLORS.length];
      const parsed = s.data.map((d) => ({
        date: d.date instanceof Date ? d.date : new Date(d.date),
        value: d.value,
      })).sort((a, b) => +a.date - +b.date);

      // Area fill
      if (showArea) {
        g.append('path').datum(parsed)
          .attr('fill', color)
          .attr('fill-opacity', 0.12)
          .attr('d', areaGen);
      }

      // Line stroke with entrance animation
      const path = g.append('path').datum(parsed)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 2)
        .attr('stroke-linejoin', 'round')
        .attr('stroke-linecap', 'round')
        .attr('d', lineGen);

      const totalLen = (path.node() as SVGPathElement).getTotalLength();
      path.attr('stroke-dasharray', `${totalLen} ${totalLen}`)
        .attr('stroke-dashoffset', totalLen)
        .transition().duration(600).ease(d3.easeCubicInOut)
        .attr('stroke-dashoffset', 0)
        .on('end', function () {
          d3.select(this).attr('stroke-dasharray', null);
        });

      // Dots
      if (showDots) {
        g.selectAll(`circle.dot-${s.id}`).data(parsed).join('circle')
          .attr('class', `dot-${s.id}`)
          .attr('cx', (d) => x(d.date))
          .attr('cy', (d) => y(d.value))
          .attr('r', 3)
          .attr('fill', color)
          .attr('opacity', 0)
          .on('mouseenter', function () { d3.select(this).attr('opacity', 1).attr('r', 5); })
          .on('mouseleave', function () { d3.select(this).attr('opacity', 0).attr('r', 3); });
      }
    });
  }, [series, width, height, showArea, showGrid, showDots, zeroLine, yFormat]);

  useEffect(() => { renderChart(); }, [renderChart]);

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}