import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { GraphNode, GraphEdge } from '../api';

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
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

const PAGE_TYPE_COLORS: Record<string, string> = {
  paper: '#a78bfa',
  entity: '#60a5fa',
  concept: '#34d399',
  overview: '#fbbf24',
  wiki_page: '#94a3b8',
  default: '#94a3b8',
};

export function GraphView({ nodes, edges, currentNode, onNodeClick, showLabels = true }: GraphViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

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

    // Define glow filter
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Create groups
    const g = svg.append('g');

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Prepare simulation data
    const simNodes: SimNode[] = nodes.map(n => ({ ...n }));
    const simEdges: SimLink[] = edges.map(e => ({ ...e }));

    // Create force simulation
    const simulation = d3.forceSimulation<SimNode>(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simEdges).id(d => d.id).distance(120).strength(0.4))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(30))
      .alphaDecay(0.02);

    simulationRef.current = simulation;

    // Draw edges
    const link = g.append('g')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simEdges)
      .join('line')
      .attr('stroke', '#475569')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', d => Math.max(1, Math.min(3, d.weight)));

    // Edge labels
    const edgeLabels = g.append('g')
      .selectAll<SVGTextElement, SimLink>('text')
      .data(simEdges)
      .join('text')
      .text(d => d.type === 'wikilink' ? '' : d.type)
      .attr('font-size', '8px')
      .attr('fill', '#64748b')
      .attr('text-anchor', 'middle')
      .attr('dy', -4);

    // Draw nodes
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

    // Node circles
    node.append('circle')
      .attr('r', d => {
        const degree = d.in_degree + d.out_degree;
        return Math.max(8, Math.min(20, 8 + degree * 2));
      })
      .attr('fill', d => {
        const color = PAGE_TYPE_COLORS[d.page_type] || PAGE_TYPE_COLORS.default;
        return d.is_current ? '#f59e0b' : color;
      })
      .attr('stroke', d => d.is_current ? '#fbbf24' : '#1e293b')
      .attr('stroke-width', d => d.is_current ? 3 : 1.5)
      .attr('filter', d => d.is_current ? 'url(#glow)' : null);

    // Node labels
    if (showLabels) {
      node.append('text')
        .text(d => {
          const label = d.label || d.id;
          return label.length > 20 ? label.slice(0, 18) + '...' : label;
        })
        .attr('font-size', '10px')
        .attr('fill', '#cbd5e1')
        .attr('text-anchor', 'middle')
        .attr('dy', d => {
          const degree = d.in_degree + d.out_degree;
          return Math.max(8, Math.min(20, 8 + degree * 2)) + 14;
        })
        .attr('pointer-events', 'none')
        .style('text-shadow', '0 1px 3px rgba(0,0,0,0.8)');
    }

    // Node click handler
    node.on('click', (event, d) => {
      event.stopPropagation();
      onNodeClick(d.id);
    });

    // Simulation tick
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

    // Initial zoom to fit
    setTimeout(() => {
      const bounds = (g.node() as SVGGElement)?.getBBox();
      if (bounds && bounds.width > 0 && bounds.height > 0) {
        const padding = 60;
        const scale = Math.min(
          width / (bounds.width + padding * 2),
          height / (bounds.height + padding * 2),
          1.5
        );
        const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
        const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
        svg.transition().duration(500).call(
          zoom.transform,
          d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }
    }, 300);

  }, [nodes, edges, dimensions, currentNode, onNodeClick, showLabels]);

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
    <div ref={containerRef} className="w-full h-full bg-slate-900">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="w-full h-full"
      />
    </div>
  );
}
