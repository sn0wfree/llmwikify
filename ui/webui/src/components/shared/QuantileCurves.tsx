/**
 * QuantileCurves — multi-group cumulative return curves.
 *
 * Displays G1-G5 quantile group cumulative returns for factor analysis.
 * Each group is a separate line, with G1 (top) and G5 (bottom) highlighted.
 *
 * Usage:
 *   <QuantileCurves
 *     groups={{
 *       G1: [{ date: '2024-01-01', value: 1.0 }, ...],
 *       G2: [...],
 *       ...
 *     }}
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface CurvePoint {
  date: Date | string | number;
  value: number;
}

interface QuantileCurvesProps {
  groups: Record<string, CurvePoint[]>;
  height?: number;
  showLegend?: boolean;
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

const MARGIN = { top: 16, right: 24, bottom: 28, left: 56 };

// ─── Component ──────────────────────────────────────────────

export function QuantileCurves({
  groups,
  height = 280,
  showLegend = true,
  className,
}: QuantileCurvesProps) {
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
    if (!svgRef.current || width === 0 || Object.keys(groups).length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
    const innerH = height - MARGIN.top - MARGIN.bottom;

    // Flatten all points
    const allPoints = Object.entries(groups).flatMap(([group, pts]) =>
      pts.map((d) => ({
        group,
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
    if (y.domain()[0] < 0 && y.domain()[1] > 0) {
      g.append('line')
        .attr('x1', 0).attr('x2', innerW)
        .attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-opacity', 0.4)
        .attr('stroke-dasharray', '4 4');
    }

    // Axes
    g.append('g').attr('transform', `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(6).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickSizeOuter(0))
      .call((sel) => sel.selectAll('text').attr('fill', 'var(--muted-foreground)').attr('font-size', '10px'))
      .call((sel) => sel.selectAll('line,path').attr('stroke', 'var(--border)'));

    // Line generator
    const lineGen = d3.line<{ date: Date; value: number }>()
      .x((d) => x(d.date))
      .y((d) => y(d.value))
      .curve(d3.curveMonotoneX);

    // Draw each group
    const groupNames = Object.keys(groups).sort();
    groupNames.forEach((group, i) => {
      const color = GROUP_COLORS[group] || `var(--chart-${(i % 5) + 1})`;
      const parsed = groups[group].map((d) => ({
        date: d.date instanceof Date ? d.date : new Date(d.date),
        value: d.value,
      })).sort((a, b) => +a.date - +b.date);

      // Line with entrance animation
      const path = g.append('path').datum(parsed)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', group === 'G1' || group === 'G5' ? 2.5 : 1.5)
        .attr('stroke-opacity', group === 'G1' || group === 'G5' ? 1 : 0.6)
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
    });

    // Legend
    if (showLegend) {
      const legend = g.append('g')
        .attr('transform', `translate(${innerW - 120}, 0)`);

      groupNames.forEach((group, i) => {
        const color = GROUP_COLORS[group] || `var(--chart-${(i % 5) + 1})`;
        const ly = i * 16;

        legend.append('line')
          .attr('x1', 0).attr('x2', 16)
          .attr('y1', ly).attr('y2', ly)
          .attr('stroke', color)
          .attr('stroke-width', group === 'G1' || group === 'G5' ? 2.5 : 1.5);

        legend.append('text')
          .attr('x', 20).attr('y', ly)
          .attr('dominant-baseline', 'middle')
          .attr('fill', 'var(--muted-foreground)')
          .attr('font-size', '10px')
          .text(group);
      });
    }
  }, [groups, width, height, showLegend]);

  useEffect(() => { renderChart(); }, [renderChart]);

  return (
    <div ref={containerRef} className={cn('w-full relative', className)}>
      <svg ref={svgRef} width={width} height={height} className="w-full" />
    </div>
  );
}