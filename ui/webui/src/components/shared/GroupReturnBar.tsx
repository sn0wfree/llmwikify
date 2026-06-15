/**
 * GroupReturnBar — horizontal bar chart for quantile group annual returns.
 *
 * Shows G1→GN annualized returns as horizontal bars with value labels.
 * Monotonic decreasing = good factor discrimination.
 *
 * Usage:
 *   <GroupReturnBar
 *     groups={{ G1: 0.243, G2: 0.187, G3: 0.142, G4: 0.098, G5: 0.031 }}
 *   />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface GroupReturnBarProps {
  groups: Record<string, number>;
  height?: number;
  className?: string;
}

// ─── Constants ──────────────────────────────────────────────

const BAR_COLORS: Record<string, string> = {
  G1: 'var(--chart-1)',
  G2: 'var(--chart-2)',
  G3: 'var(--chart-3)',
  G4: 'var(--chart-4)',
  G5: 'var(--chart-5)',
};

const MARGIN = { top: 8, right: 60, bottom: 8, left: 40 };

// ─── Component ──────────────────────────────────────────────

export function GroupReturnBar({
  groups,
  height = 180,
  className,
}: GroupReturnBarProps) {
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

    // Sort groups: G1 first
    const sorted = Object.entries(groups)
      .sort(([a], [b]) => {
        const na = parseInt(a.replace(/\D/g, ''), 10) || 0;
        const nb = parseInt(b.replace(/\D/g, ''), 10) || 0;
        return na - nb;
      });

    const groupNames = sorted.map(([k]) => k);
    const values = sorted.map(([, v]) => v);

    // Scales
    const xMin = Math.min(0, d3.min(values) || 0);
    const xMax = Math.max(0.01, d3.max(values) || 0.01);
    const xPad = (xMax - xMin) * 0.15;

    const x = d3.scaleLinear()
      .domain([xMin - xPad, xMax + xPad])
      .range([0, innerW]);

    const y = d3.scaleBand()
      .domain(groupNames)
      .range([0, innerH])
      .padding(0.3);

    const g = svg.append('g')
      .attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);

    // Zero line
    if (x.domain()[0] < 0 && x.domain()[1] > 0) {
      g.append('line')
        .attr('x1', x(0)).attr('x2', x(0))
        .attr('y1', 0).attr('y2', innerH)
        .attr('stroke', 'var(--muted-foreground)')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3 3')
        .attr('opacity', 0.5);
    }

    // Bars
    g.selectAll('rect')
      .data(sorted)
      .join('rect')
      .attr('x', (d) => d[1] >= 0 ? x(0) : x(d[1]))
      .attr('y', (d) => y(d[0])!)
      .attr('width', (d) => Math.abs(x(d[1]) - x(0)))
      .attr('height', y.bandwidth())
      .attr('fill', (d) => BAR_COLORS[d[0]] || `var(--chart-${(sorted.indexOf(d) % 5) + 1})`)
      .attr('rx', 3)
      .attr('opacity', 0.85)
      .on('mouseenter', function () {
        d3.select(this).attr('opacity', 1);
      })
      .on('mouseleave', function () {
        d3.select(this).attr('opacity', 0.85);
      });

    // Value labels
    g.selectAll('.bar-label')
      .data(sorted)
      .join('text')
      .attr('class', 'bar-label')
      .attr('x', (d) => d[1] >= 0 ? x(d[1]) + 6 : x(d[1]) - 6)
      .attr('y', (d) => (y(d[0]) || 0) + y.bandwidth() / 2)
      .attr('dominant-baseline', 'middle')
      .attr('text-anchor', (d) => d[1] >= 0 ? 'start' : 'end')
      .attr('fill', (d) => BAR_COLORS[d[0]] || 'var(--foreground)')
      .attr('font-size', '11px')
      .attr('font-weight', '600')
      .text((d) => `${(d[1] * 100).toFixed(1)}%`);

    // Y axis (group labels)
    g.append('g')
      .call(d3.axisLeft(y).tickSize(0).tickPadding(8))
      .call((sel) => sel.select('.domain').remove())
      .selectAll('text')
      .attr('fill', 'var(--muted-foreground)')
      .attr('font-size', '11px')
      .attr('font-weight', '500');

  }, [groups, width, height]);

  useEffect(() => { renderChart(); }, [renderChart]);

  if (Object.keys(groups).length === 0) {
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
