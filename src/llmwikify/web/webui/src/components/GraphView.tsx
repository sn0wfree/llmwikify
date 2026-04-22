import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { GraphNode, GraphEdge } from '../api';

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  allTypes: string[];
  currentNode: string | null;
  onNodeClick: (nodeId: string) => void;
  showLabels?: boolean;
}

interface SimNode extends GraphNode, d3.SimulationNodeDatum {}
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  source: string | SimNode;
  target: string | SimNode;
  type: string;
  weight: number;
}

const DEFAULT_COLORS = ['#a855f7', '#3b82f6', '#14b8a6', '#f97316', '#ec4899', '#ef4444', '#fbbf24', '#22c55e', '#8b5cf6', '#06b6d4'];

function getDynamicColor(pageType: string, allTypes: string[]): string {
  if (!allTypes || allTypes.length === 0) {
    return DEFAULT_COLORS[0];
  }
  const idx = allTypes.indexOf(pageType);
  if (idx === -1) return '#94a3b8';
  const hue = (idx / allTypes.length) * 360;
  const sat = 65 + (idx % 3) * 10;
  const light = 50 + (idx % 2) * 10;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

function getNodeRadius(d: SimNode): number {
  if (d.is_current) return 40;
  const degree = d.in_degree + d.out_degree;
  if (degree >= 5) return 30;
  if (degree >= 2) return 20;
  return 12;
}

interface TooltipData {
  node: SimNode;
  x: number;
  y: number;
}

export function GraphView({ nodes, edges, allTypes, currentNode, onNodeClick, showLabels = true }: GraphViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);

  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({ width: rect.width, height: rect.height });
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const renderGraph = useCallback(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const { width, height } = dimensions;

    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    filter.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const g = svg.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    const simNodes: SimNode[] = nodes.map(n => ({ ...n }));
    const simEdges: SimLink[] = edges.map(e => ({ ...e }));

    const simulation = d3.forceSimulation<SimNode>(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simEdges).id(d => (d as SimNode).id).distance(100).strength(0.5))
      .force('charge', d3.forceManyBody().strength(-500))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => getNodeRadius(d as SimNode) + 10))
      .alphaDecay(0.02);

    simulationRef.current = simulation;

    const link = g.append('g')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simEdges)
      .join('line')
      .attr('stroke', '#475569')
      .attr('stroke-opacity', d => 0.2 + Math.min(0.4, d.weight * 0.15))
      .attr('stroke-width', d => Math.max(0.5, Math.min(2.5, d.weight * 0.8)));

    const edgeLabels = g.append('g')
      .selectAll<SVGTextElement, SimLink>('text')
      .data(simEdges)
      .join('text')
      .text(d => d.type === 'wikilink' ? '' : d.type)
      .attr('font-size', '7px')
      .attr('fill', '#64748b')
      .attr('text-anchor', 'middle')
      .attr('dy', -3);

    const node = g.append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag<SVGGElement, SimNode>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }));

    node.append('circle')
      .attr('r', d => getNodeRadius(d))
      .attr('fill', d => {
        if (d.is_current) return '#fbbf24';
        return getDynamicColor(d.page_type, allTypes);
      })
      .attr('stroke', d => d.is_current ? '#fef08a' : 'rgba(30, 41, 59, 0.6)')
      .attr('stroke-width', d => d.is_current ? 3 : 1)
      .attr('filter', d => d.is_current ? 'url(#glow)' : null);

    if (showLabels) {
      node.append('text')
        .text(d => {
          const r = getNodeRadius(d);
          if (r <= 12) return '';
          const label = d.label || d.id;
          if (r <= 20 && label.length > 12) return label.slice(0, 10) + '..';
          if (r <= 30 && label.length > 16) return label.slice(0, 14) + '...';
          return label;
        })
        .attr('font-size', d => getNodeRadius(d) <= 20 ? '9px' : '11px')
        .attr('fill', '#e2e8f0')
        .attr('text-anchor', 'middle')
        .attr('dy', d => getNodeRadius(d) + 14)
        .attr('pointer-events', 'none')
        .style('text-shadow', '0 1px 4px rgba(0,0,0,0.9)');
    }

    node.on('click', (event, d) => {
      event.stopPropagation();
      onNodeClick(d.id);
    });

    node.on('mouseenter', (event, d) => {
      const r = getNodeRadius(d);
      const degree = d.in_degree + d.out_degree;
      const rect = containerRef.current?.getBoundingClientRect();
      if (rect && d.x !== undefined && d.y !== undefined) {
        setTooltip({
          node: d,
          x: d.x + rect.width / 2,
          y: d.y + rect.height / 2 - r - 35,
        });
      }
    });

    node.on('mouseleave', () => {
      setTooltip(null);
    });

    simulation.on('tick', () => {
      link
        .attr('x1', d => (d.source as SimNode).x || 0)
        .attr('y1', d => (d.source as SimNode).y || 0)
        .attr('x2', d => (d.target as SimNode).x || 0)
        .attr('y2', d => (d.target as SimNode).y || 0);

      edgeLabels
        .attr('x', d => (((d.source as SimNode).x || 0) + ((d.target as SimNode).x || 0)) / 2)
        .attr('y', d => (((d.source as SimNode).y || 0) + ((d.target as SimNode).y || 0)) / 2);

      node.attr('transform', d => `translate(${d.x || 0},${d.y || 0})`);
    });

    setTimeout(() => {
      const bounds = (g.node() as SVGGElement)?.getBBox();
      if (bounds && bounds.width > 0 && bounds.height > 0) {
        const padding = 80;
        const scale = Math.min(
          width / (bounds.width + padding * 2),
          height / (bounds.height + padding * 2),
          1.2
        );
        const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
        const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
        svg.transition().duration(500).call(
          zoom.transform,
          d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    }, 300);

  }, [nodes, edges, allTypes, dimensions, currentNode, onNodeClick, showLabels]);

  useEffect(() => {
    renderGraph();
    return () => {
      if (simulationRef.current) {
        simulationRef.current.stop();
      }
    };
  }, [renderGraph]);

  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        <div className="text-center">
          <p className="text-lg mb-2">No graph data</p>
          <p className="text-sm">Add pages with wikilinks to see the knowledge graph.</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full bg-slate-900 relative">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="w-full h-full"
      />
      {tooltip && (
        <div
          className="absolute z-20 pointer-events-none bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 shadow-xl"
          style={{
            left: Math.max(10, Math.min(dimensions.width - 150, tooltip.x)),
            top: Math.max(10, tooltip.y),
          }}
        >
          <p className="text-sm font-medium text-slate-100">{tooltip.node.label || tooltip.node.id}</p>
          <p className="text-xs text-slate-400 mt-1">
            {tooltip.node.page_type} • in: {tooltip.node.in_degree} / out: {tooltip.node.out_degree}
          </p>
        </div>
      )}
    </div>
  );
}