import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import * as d3 from 'd3';
import {
  ZoomIn, ZoomOut, Maximize2, RotateCw, Search, X, Network, Hash, Tag,
} from 'lucide-react';
import { GraphNode, GraphEdge } from '../../api';
import { LoadingState, EmptyState } from '../ui/states';
import { cn } from '@/lib/utils';

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  allTypes: string[];
  currentNode: string | null;
  onNodeClick: (nodeId: string) => void;
  showLabels?: boolean;
  isLoading?: boolean;
}

interface SimNode extends GraphNode, d3.SimulationNodeDatum {}
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  source: string | SimNode;
  target: string | SimNode;
  type: string;
  weight: number;
}

interface TooltipData {
  node: SimNode;
  x: number;
  y: number;
}

const TYPE_COLOR_VARS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5'];

function getTypeColorVar(pageType: string, allTypes: string[]): string {
  if (!allTypes || allTypes.length === 0 || !pageType) return '--muted-foreground';
  const idx = allTypes.indexOf(pageType);
  if (idx === -1) return '--muted-foreground';
  return TYPE_COLOR_VARS[idx % TYPE_COLOR_VARS.length];
}

function getEdgeTypeColorVar(type: string): string {
  const map: Record<string, string> = {
    wikilink: '--primary',
    citation: '--warning',
    reference: '--muted-foreground',
    backlink: '--chart-2',
  };
  return map[type] || '--border';
}

function getNodeRadius(d: SimNode): number {
  if (d.is_current) return 22;
  const degree = d.in_degree + d.out_degree;
  if (degree >= 8) return 20;
  if (degree >= 4) return 16;
  if (degree >= 2) return 12;
  return 8;
}

export function GraphView({
  nodes, edges, allTypes, currentNode, onNodeClick, showLabels = true, isLoading = false,
}: GraphViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const nodePositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const [, forceRender] = useState(0);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [zoomLevel, setZoomLevel] = useState(1);
  const [searchResults, setSearchResults] = useState<GraphNode[]>([]);
  const [searchIdx, setSearchIdx] = useState(0);

  // Filtered nodes/edges based on hiddenTypes
  const { visibleNodes, visibleEdges } = useMemo(() => {
    const visibleNodes = nodes.filter((n) => !hiddenTypes.has(n.page_type));
    const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = edges.filter((e) => {
      const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
      const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
      return visibleNodeIds.has(sourceId) && visibleNodeIds.has(targetId);
    });
    return { visibleNodes, visibleEdges };
  }, [nodes, edges, hiddenTypes]);

  // Search results
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      setSearchIdx(0);
      return;
    }
    const q = searchQuery.toLowerCase();
    const matched = visibleNodes.filter((n) =>
      (n.label || n.id).toLowerCase().includes(q) ||
      n.page_type?.toLowerCase().includes(q)
    );
    setSearchResults(matched.slice(0, 8));
    setSearchIdx(0);
  }, [searchQuery, visibleNodes]);

  // Resize observer
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

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;
      if (e.key === 'f') fitToView();
      if (e.key === 'r') relayout();
      if (e.key === 'Escape') {
        if (searchOpen) setSearchOpen(false);
        else if (selectedNode) setSelectedNode(null);
      }
      if (e.key === '/' && !searchOpen) {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [searchOpen, selectedNode]);

  const fitToView = useCallback(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>('g.graph-content');
    if (g.empty()) return;
    const bounds = g.node()?.getBBox();
    if (!bounds || bounds.width === 0) return;
    const padding = 80;
    const scale = Math.min(
      dimensions.width / (bounds.width + padding * 2),
      dimensions.height / (bounds.height + padding * 2),
      1.5,
    );
    const tx = dimensions.width / 2 - (bounds.x + bounds.width / 2) * scale;
    const ty = dimensions.height / 2 - (bounds.y + bounds.height / 2) * scale;
    svg.transition().duration(600).ease(d3.easeCubicInOut)
      .call(zoomRef.current!.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }, [dimensions]);

  const relayout = useCallback(() => {
    nodePositionsRef.current.clear();
    forceRender((n) => n + 1);
  }, []);

  const zoomBy = useCallback((factor: number) => {
    if (!svgRef.current || !zoomRef.current) return;
    d3.select(svgRef.current).transition().duration(200)
      .call(zoomRef.current.scaleBy, factor);
  }, []);

  // Main graph render
  const renderGraph = useCallback(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const { width, height } = dimensions;
    const isHighlighted = hoveredNode !== null || selectedNode !== null;
    const focusId = hoveredNode || selectedNode;

    // ===== <defs>: glow filter + arrow markers =====
    const defs = svg.append('defs');

    // Node glow filter
    const glow = defs.append('filter').attr('id', 'node-glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    glow.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = glow.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Current node pulse filter
    const pulseGlow = defs.append('filter').attr('id', 'current-pulse').attr('x', '-100%').attr('y', '-100%').attr('width', '300%').attr('height', '300%');
    pulseGlow.append('feGaussianBlur').attr('stdDeviation', '5').attr('result', 'coloredBlur');
    const feMerge2 = pulseGlow.append('feMerge');
    feMerge2.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge2.append('feMergeNode').attr('in', 'SourceGraphic');

    // Arrow markers per edge type
    const edgeTypesInUse = new Set(visibleEdges.map((e) => e.type));
    edgeTypesInUse.forEach((type) => {
      const color = getEdgeTypeColorVar(type);
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 8)
        .attr('refY', 0)
        .attr('markerWidth', 5)
        .attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4')
        .attr('fill', `var(${color})`)
        .attr('opacity', 0.6);
    });

    // ===== Zoom behavior =====
    const g = svg.append('g').attr('class', 'graph-content');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
        setZoomLevel(event.transform.k);
      });

    zoomRef.current = zoom;
    svg.call(zoom);

    // ===== Build simulation nodes & links =====
    const simNodes: SimNode[] = visibleNodes.map((n) => {
      const savedPos = nodePositionsRef.current.get(n.id);
      return {
        ...n,
        x: savedPos?.x ?? width / 2 + (Math.random() - 0.5) * 200,
        y: savedPos?.y ?? height / 2 + (Math.random() - 0.5) * 200,
      };
    });

    const simLinks: SimLink[] = visibleEdges.map((e) => ({ ...e }));

    // ===== Force simulation =====
    const simulation = d3.forceSimulation<SimNode>(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance((d) => 60 + (1 - Math.min(1, d.weight / 5)) * 60)
        .strength((d) => Math.min(0.7, d.weight * 0.15)),
      )
      .force('charge', d3.forceManyBody<SimNode>().strength((d) => -200 - getNodeRadius(d) * 10))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<SimNode>().radius((d) => getNodeRadius(d) + 8))
      .force('x', d3.forceX(width / 2).strength(0.04))
      .force('y', d3.forceY(height / 2).strength(0.04))
      .alphaDecay(0.025)
      .alphaMin(0.05);

    simulationRef.current = simulation;

    // ===== Edges =====
    const link = g.append('g')
      .attr('class', 'edges')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', (d) => `var(${getEdgeTypeColorVar(d.type)})`)
      .attr('stroke-opacity', (d) => 0.25 + Math.min(0.5, d.weight * 0.15))
      .attr('stroke-width', (d) => Math.max(0.6, Math.sqrt(d.weight) * 1.8))
      .attr('marker-end', (d) => `url(#arrow-${d.type})`);

    // ===== Edge labels =====
    const edgeLabels = g.append('g')
      .attr('class', 'edge-labels')
      .selectAll<SVGTextElement, SimLink>('text')
      .data(simLinks)
      .join('text')
      .text((d) => (d.type === 'wikilink' ? '' : d.type))
      .attr('font-size', '8px')
      .attr('fill', 'var(--muted-foreground)')
      .attr('text-anchor', 'middle')
      .attr('dy', -3)
      .attr('pointer-events', 'none')
      .style('text-shadow', '0 1px 3px var(--background)');

    // ===== Nodes =====
    const node = g.append('g')
      .attr('class', 'nodes')
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
        }),
      );

    // Outer ring (for hub nodes)
    node.filter((d) => (d.in_degree + d.out_degree) >= 5 && !d.is_current)
      .append('circle')
      .attr('class', 'hub-ring')
      .attr('r', (d) => getNodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', (d) => `var(${getTypeColorVar(d.page_type, allTypes)})`)
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.4)
      .attr('stroke-dasharray', '2 3');

    // Main node circle
    node.append('circle')
      .attr('class', 'node-circle')
      .attr('r', (d) => getNodeRadius(d))
      .attr('fill', (d) => {
        if (d.is_current) return 'var(--primary)';
        return `var(${getTypeColorVar(d.page_type, allTypes)})`;
      })
      .attr('stroke', (d) => {
        if (d.is_current) return 'var(--accent)';
        return 'var(--background)';
      })
      .attr('stroke-width', (d) => (d.is_current ? 3 : 2))
      .attr('filter', (d) => (d.is_current ? 'url(#current-pulse)' : null));

    // Pulse animation for current node
    node.filter((d) => !!d.is_current)
      .select<SVGCircleElement>('circle.node-circle')
      .transition()
      .duration(1500)
      .ease(d3.easeCubicInOut)
      .attr('r', (d) => getNodeRadius(d) * 1.25)
      .transition()
      .attr('r', (d) => getNodeRadius(d))
      .on('end', function repeat() {
        d3.select<SVGCircleElement, SimNode>(this as SVGCircleElement)
          .transition()
          .duration(1500)
          .ease(d3.easeCubicInOut)
          .attr('r', (d) => getNodeRadius(d) * 1.25)
          .transition()
          .attr('r', (d) => getNodeRadius(d))
          .on('end', repeat);
      });

    // Labels
    if (showLabels) {
      node.append('text')
        .attr('class', 'node-label')
        .text((d) => {
          const r = getNodeRadius(d);
          if (r <= 8) return '';
          const label = d.label || d.id;
          if (r <= 12 && label.length > 8) return label.slice(0, 6) + '..';
          if (r <= 16 && label.length > 12) return label.slice(0, 10) + '..';
          return label;
        })
        .attr('font-size', (d) => (getNodeRadius(d) <= 12 ? '8px' : '10px'))
        .attr('font-weight', (d) => (d.is_current ? 600 : 400))
        .attr('fill', (d) => (d.is_current ? 'var(--primary-foreground)' : 'var(--foreground)'))
        .attr('text-anchor', 'middle')
        .attr('dy', (d) => getNodeRadius(d) + 12)
        .attr('pointer-events', 'none')
        .style('text-shadow', '0 1px 4px var(--background), 0 0 8px var(--background)');
    }

    // Click → select & navigate
    node.on('click', (event, d) => {
      event.stopPropagation();
      setSelectedNode((prev) => (prev === d.id ? null : d.id));
      onNodeClick(d.id);
    });

    // Hover → highlight neighbors
    node.on('mouseenter', (event, d) => {
      setHoveredNode(d.id);
      const neighborIds = new Set<string>([d.id]);
      visibleEdges.forEach((e) => {
        const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
        const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
        if (sourceId === d.id) neighborIds.add(targetId as string);
        if (targetId === d.id) neighborIds.add(sourceId as string);
      });

      node.style('opacity', (n) => (neighborIds.has(n.id) ? 1 : 0.2));
      link.style('opacity', (e) => {
        const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
        const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
        return (sourceId === d.id || targetId === d.id) ? Math.min(1, 0.4 + e.weight * 0.2) : 0.05;
      });
      edgeLabels.style('opacity', (e) => {
        const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
        const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
        return (sourceId === d.id || targetId === d.id) ? 1 : 0.05;
      });

      // Position tooltip
      const rect = containerRef.current?.getBoundingClientRect();
      if (rect && d.x !== undefined && d.y !== undefined) {
        const r = getNodeRadius(d);
        setTooltip({
          node: d,
          x: d.x + rect.width / 2,
          y: d.y + rect.height / 2 - r - 30,
        });
      }
    });

    node.on('mouseleave', () => {
      setHoveredNode(null);
      setTooltip(null);
      if (!isHighlighted) {
        node.style('opacity', 1);
        link.style('opacity', null);
        edgeLabels.style('opacity', 1);
      } else if (selectedNode) {
        // Re-apply selection highlight
        const neighborIds = new Set<string>([selectedNode]);
        visibleEdges.forEach((e) => {
          const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
          const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
          if (sourceId === selectedNode) neighborIds.add(targetId as string);
          if (targetId === selectedNode) neighborIds.add(sourceId as string);
        });
        node.style('opacity', (n) => (neighborIds.has(n.id) ? 1 : 0.3));
        link.style('opacity', (e) => {
          const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
          const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
          return (sourceId === selectedNode || targetId === selectedNode) ? Math.min(1, 0.4 + e.weight * 0.2) : 0.1;
        });
        edgeLabels.style('opacity', (e) => {
          const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
          const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
          return (sourceId === selectedNode || targetId === selectedNode) ? 1 : 0.1;
        });
      } else {
        node.style('opacity', 1);
        link.style('opacity', null);
        edgeLabels.style('opacity', 1);
      }
    });

    // Apply selection highlight on initial render
    if (selectedNode) {
      const neighborIds = new Set<string>([selectedNode]);
      visibleEdges.forEach((e) => {
        const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
        const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
        if (sourceId === selectedNode) neighborIds.add(targetId as string);
        if (targetId === selectedNode) neighborIds.add(sourceId as string);
      });
      node.style('opacity', (n) => (neighborIds.has(n.id) ? 1 : 0.3));
      link.style('opacity', (e) => {
        const sourceId = typeof e.source === 'string' ? e.source : (e.source as SimNode)?.id;
        const targetId = typeof e.target === 'string' ? e.target : (e.target as SimNode)?.id;
        return (sourceId === selectedNode || targetId === selectedNode) ? Math.min(1, 0.4 + e.weight * 0.2) : 0.1;
      });
    }

    // Click empty → clear selection
    svg.on('click', () => {
      setSelectedNode(null);
    });

    // ===== Tick =====
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimNode).x || 0)
        .attr('y1', (d) => (d.source as SimNode).y || 0)
        .attr('x2', (d) => (d.target as SimNode).x || 0)
        .attr('y2', (d) => (d.target as SimNode).y || 0);

      edgeLabels
        .attr('x', (d) => (((d.source as SimNode).x || 0) + ((d.target as SimNode).x || 0)) / 2)
        .attr('y', (d) => (((d.source as SimNode).y || 0) + ((d.target as SimNode).y || 0)) / 2);

      node.attr('transform', (d) => `translate(${d.x || 0},${d.y || 0})`);

      simNodes.forEach((n) => {
        if (n.x !== undefined && n.y !== undefined) {
          nodePositionsRef.current.set(n.id, { x: n.x, y: n.y });
        }
      });
    });

    // Auto fit after stabilization
    setTimeout(() => {
      const bounds = g.node()?.getBBox();
      if (bounds && bounds.width > 0 && bounds.height > 0) {
        const padding = 100;
        const scale = Math.min(
          width / (bounds.width + padding * 2),
          height / (bounds.height + padding * 2),
          1.2,
        );
        const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
        const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
        svg.transition().duration(750).ease(d3.easeCubicInOut)
          .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    }, 1000);

  }, [visibleNodes, visibleEdges, allTypes, dimensions, currentNode, onNodeClick, showLabels, selectedNode, hoveredNode]);

  useEffect(() => {
    renderGraph();
    return () => {
      if (simulationRef.current) simulationRef.current.stop();
    };
  }, [renderGraph]);

  // Center on search result
  const focusOnNode = useCallback((nodeId: string) => {
    const pos = nodePositionsRef.current.get(nodeId);
    if (!pos || !svgRef.current || !zoomRef.current) return;
    const scale = 1.5;
    const tx = dimensions.width / 2 - pos.x * scale;
    const ty = dimensions.height / 2 - pos.y * scale;
    d3.select(svgRef.current).transition().duration(600).ease(d3.easeCubicInOut)
      .call(zoomRef.current.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    setSelectedNode(nodeId);
  }, [dimensions]);

  const toggleType = (type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  // ==================== Render ====================
  if (isLoading) {
    return <LoadingState message="Loading graph…" />;
  }

  if (visibleNodes.length === 0 && nodes.length > 0) {
    return (
      <EmptyState
        icon={<Network className="w-6 h-6" />}
        title="All types hidden"
        description="Toggle page types in the legend to see nodes."
      />
    );
  }

  if (nodes.length === 0) {
    return (
      <EmptyState
        icon={<Network className="w-6 h-6" />}
        title="No graph data"
        description="Add pages with wikilinks to see the knowledge graph."
      />
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full relative overflow-hidden">
      {/* Background grid */}
      <div
        className="absolute inset-0 pointer-events-none opacity-30"
        style={{
          backgroundImage: 'radial-gradient(circle at 1px 1px, var(--border) 1px, transparent 0)',
          backgroundSize: '24px 24px',
        }}
      />

      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="w-full h-full"
      />

      {/* Top-left: control bar */}
      <div className="absolute top-3 left-3 flex flex-col gap-2 z-20">
        <div className="glass-strong rounded-lg p-1 flex flex-col gap-0.5">
          <ControlButton onClick={() => zoomBy(1.3)} title="Zoom in (+)">
            <ZoomIn className="w-3.5 h-3.5" />
          </ControlButton>
          <ControlButton onClick={() => zoomBy(0.77)} title="Zoom out (-)">
            <ZoomOut className="w-3.5 h-3.5" />
          </ControlButton>
          <ControlButton onClick={fitToView} title="Fit to view (f)">
            <Maximize2 className="w-3.5 h-3.5" />
          </ControlButton>
          <ControlButton onClick={relayout} title="Re-layout (r)">
            <RotateCw className="w-3.5 h-3.5" />
          </ControlButton>
          <ControlButton
            onClick={() => setSearchOpen((v) => !v)}
            title="Search nodes (/)"
            active={searchOpen}
          >
            <Search className="w-3.5 h-3.5" />
          </ControlButton>
        </div>
      </div>

      {/* Top-right: search panel */}
      {searchOpen && (
        <div className="absolute top-3 right-3 z-20 w-72 glass-strong rounded-lg shadow-elevated overflow-hidden animate-slide-up">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
            <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <input
              autoFocus
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const n = searchResults[searchIdx];
                  if (n) {
                    focusOnNode(n.id);
                    setSearchOpen(false);
                  }
                } else if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setSearchIdx((i) => Math.min(searchResults.length - 1, i + 1));
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setSearchIdx((i) => Math.max(0, i - 1));
                }
              }}
              placeholder="Search nodes…"
              className="flex-1 bg-transparent border-0 outline-none text-xs text-foreground placeholder:text-muted-foreground"
            />
            <button
              onClick={() => { setSearchOpen(false); setSearchQuery(''); }}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {searchResults.length === 0 ? (
              <div className="p-4 text-center text-[10px] text-muted-foreground">
                {searchQuery ? 'No matches' : 'Type to search'}
              </div>
            ) : (
              searchResults.map((n, i) => (
                <button
                  key={n.id}
                  onClick={() => { focusOnNode(n.id); setSearchOpen(false); }}
                  className={cn(
                    'w-full text-left px-3 py-2 border-b border-border/30 last:border-b-0 transition-colors flex items-center gap-2',
                    i === searchIdx ? 'bg-primary/15' : 'hover:bg-white/[0.04]',
                  )}
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: `var(${getTypeColorVar(n.page_type, allTypes)})` }}
                  />
                  <span className="text-xs font-medium text-foreground truncate flex-1">
                    {n.label || n.id}
                  </span>
                  <span className="text-[10px] text-muted-foreground font-mono shrink-0">
                    {n.page_type}
                  </span>
                </button>
              ))
            )}
          </div>
          <div className="px-3 py-1.5 text-[10px] text-muted-foreground border-t border-border/30 flex items-center gap-2">
            <kbd className="px-1 rounded bg-white/[0.06] text-[9px]">↑↓</kbd>
            <span>navigate</span>
            <kbd className="px-1 rounded bg-white/[0.06] text-[9px] ml-auto">↵</kbd>
            <span>go</span>
          </div>
        </div>
      )}

      {/* Bottom-left: legend */}
      {allTypes.length > 0 && (
        <div className="absolute bottom-3 left-3 z-20 glass-strong rounded-lg p-2 max-w-[200px]">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-1 pb-1.5 mb-1 border-b border-border/30">
            Types
          </div>
          <div className="space-y-0.5">
            {allTypes.map((type) => {
              const count = visibleNodes.filter((n) => n.page_type === type).length;
              const total = nodes.filter((n) => n.page_type === type).length;
              const hidden = hiddenTypes.has(type);
              return (
                <button
                  key={type}
                  onClick={() => toggleType(type)}
                  className={cn(
                    'w-full flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[10px] transition-colors',
                    hidden ? 'opacity-40' : 'hover:bg-white/[0.04]',
                  )}
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0 ring-1 ring-border/30"
                    style={{ background: `var(${getTypeColorVar(type, allTypes)})` }}
                  />
                  <span className="text-foreground/85 truncate flex-1 text-left">{type}</span>
                  <span className="text-muted-foreground font-mono tabular-nums shrink-0">
                    {hidden ? total : count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Bottom: info bar */}
      <div className="absolute bottom-3 right-3 z-20 glass-strong rounded-lg px-3 py-1.5 flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Hash className="w-3 h-3" />
          <span className="font-mono tabular-nums">{visibleNodes.length}</span>
          <span className="font-mono">nodes</span>
        </span>
        <span className="opacity-50">·</span>
        <span className="flex items-center gap-1">
          <Tag className="w-3 h-3" />
          <span className="font-mono tabular-nums">{visibleEdges.length}</span>
          <span className="font-mono">edges</span>
        </span>
        <span className="opacity-50">·</span>
        <span className="font-mono tabular-nums">{Math.round(zoomLevel * 100)}%</span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute z-30 pointer-events-none glass-strong rounded-lg px-3 py-2 shadow-elevated animate-fade-in"
          style={{
            left: Math.max(10, Math.min(dimensions.width - 220, tooltip.x)),
            top: Math.max(10, tooltip.y),
          }}
        >
          <div className="flex items-center gap-1.5">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: `var(${getTypeColorVar(tooltip.node.page_type, allTypes)})` }}
            />
            <p className="text-xs font-semibold text-foreground truncate max-w-[180px]">
              {tooltip.node.label || tooltip.node.id}
            </p>
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
            <span className="font-mono">{tooltip.node.page_type}</span>
            <span className="opacity-50">·</span>
            <span>in: <span className="text-foreground/80 font-mono">{tooltip.node.in_degree}</span></span>
            <span className="opacity-50">·</span>
            <span>out: <span className="text-foreground/80 font-mono">{tooltip.node.out_degree}</span></span>
          </div>
        </div>
      )}
    </div>
  );
}

function ControlButton({
  onClick, title, children, active,
}: {
  onClick: () => void;
  title: string;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={cn(
        'w-7 h-7 rounded-md flex items-center justify-center transition-colors',
        active
          ? 'bg-primary/20 text-primary'
          : 'text-muted-foreground hover:bg-white/[0.06] hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}
