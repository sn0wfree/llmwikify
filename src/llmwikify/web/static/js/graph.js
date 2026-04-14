/**
 * llmwikify Web UI - Knowledge Graph Visualization (D3.js)
 */

class GraphView {
    constructor(api, onPageClick) {
        this.api = api;
        this.onPageClick = onPageClick;
        this.svg = null;
        this.simulation = null;
        this.graphData = { nodes: [], edges: [] };
        this.allNodes = [];
        this.allEdges = [];
        this.heightlightedNodes = new Set();
        this.isFiltered = false;
    }

    async open() {
        const modal = document.getElementById('graph-modal');
        modal.classList.remove('hidden');
        await this.loadData();
        this.setupInteractions();
    }

    close() {
        const modal = document.getElementById('graph-modal');
        modal.classList.add('hidden');
        if (this.simulation) {
            this.simulation.stop();
        }
    }

    async loadData() {
        const container = document.getElementById('graph-container');
        container.innerHTML = '<div class="loading">Loading graph...</div>';

        try {
            const data = await this.api.wiki_graph_analyze('export', { format: 'html' });
            // The MCP tool exports to HTML file, we need raw graph data
            // Fall back to building from wiki_graph stats + references
            await this.buildFromReferences();
        } catch (e) {
            console.warn('Graph export failed, building from references:', e);
            await this.buildFromReferences();
        }
    }

    async buildFromReferences() {
        try {
            const status = await this.api.wiki_status();
            const pagesByType = status.pages_by_type || {};
            const allPages = Object.values(pagesByType).flat();

            if (allPages.length === 0) {
                document.getElementById('graph-container').innerHTML =
                    '<div class="empty-state"><h2>No pages</h2><p>Create some pages first.</p></div>';
                return;
            }

            const nodesMap = new Map();
            const edges = [];

            // Create nodes for all pages
            for (const pageName of allPages) {
                nodesMap.set(pageName, {
                    id: pageName,
                    label: pageName,
                    type: 'entity',
                    hasPage: true,
                    degree: 0,
                });
            }

            // Fetch references for each page to build edges
            const batchSize = 5;
            for (let i = 0; i < allPages.length; i += batchSize) {
                const batch = allPages.slice(i, i + batchSize);
                const promises = batch.map(async (pageName) => {
                    try {
                        const refs = await this.api.wiki_references(pageName, false);
                        const outbound = refs.outbound || [];
                        for (const link of outbound) {
                            const target = link.target_page || link.target;
                            if (target && target !== pageName) {
                                // Ensure target node exists
                                if (!nodesMap.has(target)) {
                                    nodesMap.set(target, {
                                        id: target,
                                        label: target,
                                        type: 'concept',
                                        hasPage: false,
                                        degree: 0,
                                    });
                                }
                                edges.push({
                                    source: pageName,
                                    target: target,
                                    type: 'wikilink',
                                });
                            }
                        }
                    } catch (e) {
                        console.warn(`Failed to fetch refs for ${pageName}:`, e);
                    }
                });
                await Promise.all(promises);
            }

            // Calculate degrees
            const degreeCount = {};
            for (const edge of edges) {
                degreeCount[edge.source] = (degreeCount[edge.source] || 0) + 1;
                degreeCount[edge.target] = (degreeCount[edge.target] || 0) + 1;
            }

            const nodes = Array.from(nodesMap.values());
            for (const node of nodes) {
                node.degree = degreeCount[node.id] || 0;
            }

            // Remove isolated nodes (except if they have pages)
            const connectedNodes = nodes.filter(n => n.degree > 0 || n.hasPage);

            this.allNodes = connectedNodes;
            this.allEdges = edges;
            this.graphData = { nodes: connectedNodes, edges };

            this.render();
        } catch (err) {
            console.error('Failed to build graph:', err);
            document.getElementById('graph-container').innerHTML =
                '<div class="empty-state"><h2>Failed to load graph</h2><p>' + err.message + '</p></div>';
        }
    }

    render() {
        const container = document.getElementById('graph-container');
        container.innerHTML = '';

        const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svgEl.id = 'graph-svg';
        svgEl.setAttribute('width', '100%');
        svgEl.setAttribute('height', '600');
        container.appendChild(svgEl);

        // Add tooltip
        const tooltip = document.createElement('div');
        tooltip.id = 'graph-tooltip';
        tooltip.className = 'graph-tooltip hidden';
        container.appendChild(tooltip);

        const width = container.clientWidth;
        const height = 600;

        this.svg = d3.select(svgEl)
            .attr('viewBox', [0, 0, width, height]);

        // Clear previous
        this.svg.selectAll('*').remove();

        // Define arrow markers
        const defs = this.svg.append('defs');
        defs.append('marker')
            .attr('id', 'arrow-wikilink')
            .attr('viewBox', '0 -5 10 10')
            .attr('refX', 25)
            .attr('refY', 0)
            .attr('markerWidth', 6)
            .attr('markerHeight', 6)
            .attr('orient', 'auto')
            .append('path')
            .attr('d', 'M0,-5L10,0L0,5')
            .attr('fill', '#a6adc8');

        defs.append('marker')
            .attr('id', 'arrow-relation')
            .attr('viewBox', '0 -5 10 10')
            .attr('refX', 25)
            .attr('refY', 0)
            .attr('markerWidth', 6)
            .attr('markerHeight', 6)
            .attr('orient', 'auto')
            .append('path')
            .attr('d', 'M0,-5L10,0L0,5')
            .attr('fill', '#6c7086');

        // Color scale for communities (we'll use degree-based coloring)
        const color = d3.scaleOrdinal()
            .domain(['entity', 'concept'])
            .range(['#a6e3a1', '#89b4fa']);

        // Zoom behavior
        const g = this.svg.append('g');

        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => {
                g.attr('transform', event.transform);
            });

        this.svg.call(zoom);

        // Force simulation
        this.simulation = d3.forceSimulation(this.graphData.nodes)
            .force('link', d3.forceLink(this.graphData.edges)
                .id(d => d.id)
                .distance(80)
                .strength(0.4))
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(30))
            .force('x', d3.forceX(width / 2).strength(0.05))
            .force('y', d3.forceY(height / 2).strength(0.05));

        // Edges
        const link = g.append('g')
            .selectAll('line')
            .data(this.graphData.edges)
            .join('line')
            .attr('stroke', d => d.type === 'wikilink' ? '#a6adc8' : '#6c7086')
            .attr('stroke-width', 1.5)
            .attr('stroke-dasharray', d => d.type === 'relation' ? '4,4' : null)
            .attr('marker-end', d => d.type === 'wikilink' ? 'url(#arrow-wikilink)' : 'url(#arrow-relation)');

        // Node groups
        const node = g.append('g')
            .selectAll('g')
            .data(this.graphData.nodes)
            .join('g')
            .attr('class', 'graph-node')
            .call(d3.drag()
                .on('start', (event, d) => {
                    if (!event.active) this.simulation.alphaTarget(0.3).restart();
                    d.fx = d.x;
                    d.fy = d.y;
                })
                .on('drag', (event, d) => {
                    d.fx = event.x;
                    d.fy = event.y;
                })
                .on('end', (event, d) => {
                    if (!event.active) this.simulation.alphaTarget(0);
                    d.fx = null;
                    d.fy = null;
                }));

        // Node circles
        node.append('circle')
            .attr('r', d => Math.max(8, Math.min(20, 6 + Math.sqrt(d.degree) * 3)))
            .attr('fill', d => color(d.type))
            .attr('stroke', d => d.hasPage ? '#4ade80' : 'transparent')
            .attr('stroke-width', 2)
            .attr('opacity', 0.9);

        // Node labels
        node.append('text')
            .text(d => d.label.length > 20 ? d.label.substring(0, 18) + '...' : d.label)
            .attr('x', d => Math.max(10, Math.min(20, 6 + Math.sqrt(d.degree) * 3)) + 4)
            .attr('y', 4)
            .attr('font-size', '10px')
            .attr('fill', '#cdd6f4')
            .attr('pointer-events', 'none')
            .attr('text-shadow', '0 1px 3px rgba(0,0,0,0.8)');

        // Node interactions
        node.on('mouseover', (event, d) => {
            const tooltipEl = document.getElementById('graph-tooltip');
            tooltipEl.classList.remove('hidden');
            tooltipEl.innerHTML = `
                <div class="tooltip-title">${d.label}</div>
                <div class="tooltip-type">Type: ${d.type} | Degree: ${d.degree} | ${d.hasPage ? 'Has page' : 'No page'}</div>
            `;
            tooltipEl.style.left = (event.pageX + 12) + 'px';
            tooltipEl.style.top = (event.pageY - 12) + 'px';

            // Highlight connected nodes
            const connected = new Set();
            connected.add(d.id);
            for (const edge of this.graphData.edges) {
                if (edge.source.id === d.id) connected.add(edge.target.id);
                if (edge.target.id === d.id) connected.add(edge.source.id);
            }

            node.select('circle').attr('opacity', n => connected.has(n.id) ? 1 : 0.15);
            link.attr('opacity', l =>
                (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.05);
        })
        .on('mouseout', () => {
            document.getElementById('graph-tooltip').classList.add('hidden');
            node.select('circle').attr('opacity', 0.9);
            link.attr('opacity', 1);
        })
        .on('click', (event, d) => {
            if (d.hasPage) {
                this.close();
                this.onPageClick(d.id);
            }
        });

        // Tick
        this.simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

        // Initial alpha
        this.simulation.alpha(1).restart();
    }

    setupInteractions() {
        // Refresh button
        const refreshBtn = document.getElementById('btn-graph-refresh');
        if (refreshBtn) {
            refreshBtn.onclick = () => this.loadData();
        }

        // Search nodes
        const searchInput = document.getElementById('graph-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase().trim();
                if (!query) {
                    this.resetHighlight();
                    return;
                }

                const matching = new Set();
                for (const node of this.allNodes) {
                    if (node.label.toLowerCase().includes(query)) {
                        matching.add(node.id);
                    }
                }

                d3.selectAll('.graph-node').select('circle')
                    .attr('opacity', d => matching.has(d.id) ? 1 : 0.1);

                d3.selectAll('.graph-node').select('text')
                    .attr('opacity', d => matching.has(d.id) ? 1 : 0.1);

                d3.select('#graph-svg').selectAll('line')
                    .attr('opacity', d =>
                        (matching.has(d.source.id) || matching.has(d.target.id)) ? 0.5 : 0.05);
            });
        }

        // Filter by degree
        const filterBtn = document.getElementById('btn-graph-filter');
        if (filterBtn) {
            filterBtn.onclick = () => {
                this.isFiltered = !this.isFiltered;
                if (this.isFiltered) {
                    // Show only nodes with degree >= 2
                    const filtered = this.graphData.nodes.filter(n => n.degree >= 2);
                    const filteredIds = new Set(filtered.map(n => n.id));
                    const filteredEdges = this.graphData.edges.filter(e =>
                        filteredIds.has(e.source.id) && filteredIds.has(e.target.id));

                    d3.selectAll('.graph-node').select('circle')
                        .attr('opacity', d => filteredIds.has(d.id) ? 1 : 0.05);

                    d3.selectAll('.graph-node').select('text')
                        .attr('opacity', d => filteredIds.has(d.id) ? 1 : 0.05);

                    d3.select('#graph-svg').selectAll('line')
                        .attr('opacity', d =>
                            (filteredIds.has(d.source.id) && filteredIds.has(d.target.id)) ? 1 : 0.05);
                } else {
                    this.resetHighlight();
                }
            };
        }

        // Close button
        const closeBtn = document.getElementById('btn-close-graph');
        if (closeBtn) {
            closeBtn.onclick = () => this.close();
        }

        // Close on modal background click
        const modal = document.getElementById('graph-modal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.close();
            });
        }
    }

    resetHighlight() {
        d3.selectAll('.graph-node').select('circle').attr('opacity', 0.9);
        d3.selectAll('.graph-node').select('text').attr('opacity', 1);
        d3.select('#graph-svg').selectAll('line').attr('opacity', 1);
        this.isFiltered = false;
    }
}
