/**
 * llmwikify Web UI - Knowledge Graph Visualization (D3.js)
 * Uses wiki_graph_analyze('analyze') for PageRank, communities, and suggestions.
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
        this.highlightedNodes = new Set();
        this.isFiltered = false;
        this.analysisData = null;
        this.communityColors = [
            '#a6e3a1', '#89b4fa', '#f9e2af', '#f38ba8',
            '#cba6f7', '#fab387', '#94e2d5', '#74c7ec',
        ];
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
        container.innerHTML = '<div class="loading">Loading graph analysis...</div>';

        try {
            this.analysisData = await this.api.wiki_graph_analyze('analyze');
            await this.buildFromAnalysis();
        } catch (e) {
            console.warn('Graph analyze failed, falling back to references:', e);
            container.innerHTML = '<div class="loading">Building graph from references...</div>';
            await this.buildFromReferences();
        }
    }

    async buildFromAnalysis() {
        const data = this.analysisData;
        if (!data) {
            await this.buildFromReferences();
            return;
        }

        const container = document.getElementById('graph-container');

        const pages = data.pages || [];
        const relations = data.relations || [];
        const centrality = data.centrality || {};
        const communities = data.communities || {};
        const suggestions = data.suggestions || {};

        if (pages.length === 0) {
            container.innerHTML =
                '<div class="empty-state"><h2>No pages</h2><p>Create some pages first.</p></div>';
            return;
        }

        const nodesMap = new Map();
        const edges = [];

        // Build PageRank lookup
        const pageRankMap = {};
        const topPages = centrality.top_pages || [];
        for (const entry of topPages) {
            pageRankMap[entry.page] = entry.score;
        }
        // Default score for pages not in top list
        const defaultScore = topPages.length > 0 ? topPages[topPages.length - 1].score * 0.5 : 0.01;

        // Build community lookup
        const communityMap = {};
        const communityList = communities.community_list || [];
        for (let i = 0; i < communityList.length; i++) {
            const comm = communityList[i];
            const members = comm.members || [];
            const label = comm.label || `Community ${i + 1}`;
            for (const member of members) {
                communityMap[member] = { index: i, label };
            }
        }

        // Identify bridge nodes
        const bridgeNodes = new Set();
        const bridges = communities.bridge_nodes || [];
        for (const b of bridges) {
            bridgeNodes.add(b.node || b);
        }

        // Create nodes for all pages
        for (const page of pages) {
            const pageName = page.page_name || page.name;
            const score = pageRankMap[pageName] || defaultScore;
            const commInfo = communityMap[pageName];
            const isBridge = bridgeNodes.has(pageName);

            nodesMap.set(pageName, {
                id: pageName,
                label: pageName,
                type: 'entity',
                hasPage: true,
                score: score,
                degree: page.out_degree || 0,
                community: commInfo ? commInfo.index : -1,
                communityLabel: commInfo ? commInfo.label : 'Unclassified',
                isBridge: isBridge,
            });
        }

        // Build edges from relations
        for (const rel of relations) {
            const source = rel.source;
            const target = rel.target;
            const relType = rel.relation_type || 'related_to';

            if (source && target && source !== target) {
                if (!nodesMap.has(target)) {
                    const commInfo = communityMap[target];
                    nodesMap.set(target, {
                        id: target,
                        label: target,
                        type: 'concept',
                        hasPage: false,
                        score: defaultScore,
                        degree: 1,
                        community: commInfo ? commInfo.index : -1,
                        communityLabel: commInfo ? commInfo.label : 'Unclassified',
                        isBridge: bridgeNodes.has(target),
                    });
                }
                edges.push({
                    source,
                    target,
                    type: 'relation',
                    relationType: relType,
                });
            }
        }

        // Also add wikilink edges from page outbound links
        for (const page of pages) {
            const pageName = page.page_name || page.name;
            const outbound = page.outbound_links || [];
            for (const link of outbound) {
                const target = typeof link === 'string' ? link : (link.target || link.target_page);
                if (target && target !== pageName && !edges.find(e => e.source === pageName && e.target === target)) {
                    if (!nodesMap.has(target)) {
                        nodesMap.set(target, {
                            id: target,
                            label: target,
                            type: 'concept',
                            hasPage: false,
                            score: defaultScore,
                            degree: 1,
                            community: -1,
                            communityLabel: 'Unclassified',
                            isBridge: false,
                        });
                    }
                    edges.push({
                        source: pageName,
                        target: target,
                        type: 'wikilink',
                        relationType: 'wikilink',
                    });
                }
            }
        }

        // Add suggested pages as ghost nodes (dashed outline in UI)
        const suggestedPages = suggestions.suggested_pages || [];
        for (const sugg of suggestedPages) {
            const pageName = sugg.page_name || sugg.page;
            if (!nodesMap.has(pageName)) {
                nodesMap.set(pageName, {
                    id: pageName,
                    label: pageName,
                    type: 'suggested',
                    hasPage: false,
                    score: 0,
                    degree: 0,
                    community: -1,
                    communityLabel: 'Suggested',
                    isBridge: false,
                    reason: sugg.reason || 'Orphan concept',
                });
            }
        }

        const nodes = Array.from(nodesMap.values());

        // Remove isolated suggested nodes (they have no edges yet)
        const connectedNodes = nodes.filter(n => n.degree > 0 || n.hasPage || (n.type === 'suggested' && nodes.length < 50));

        this.allNodes = connectedNodes;
        this.allEdges = edges;
        this.graphData = { nodes: connectedNodes, edges };

        // Store community count for legend
        this.communityCount = Math.max(0, ...communityList.map((_, i) => i)) + 1;
        this.communityLabels = communityList.map(c => c.label || 'Unknown');

        this.render();
        this.renderAnalysisSummary();
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

            for (const pageName of allPages) {
                nodesMap.set(pageName, {
                    id: pageName,
                    label: pageName,
                    type: 'entity',
                    hasPage: true,
                    score: 0,
                    degree: 0,
                    community: -1,
                    communityLabel: 'N/A',
                    isBridge: false,
                });
            }

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
                                if (!nodesMap.has(target)) {
                                    nodesMap.set(target, {
                                        id: target,
                                        label: target,
                                        type: 'concept',
                                        hasPage: false,
                                        score: 0,
                                        degree: 0,
                                        community: -1,
                                        communityLabel: 'N/A',
                                        isBridge: false,
                                    });
                                }
                                edges.push({
                                    source: pageName,
                                    target: target,
                                    type: 'wikilink',
                                    relationType: 'wikilink',
                                });
                            }
                        }
                    } catch (e) {
                        console.warn(`Failed to fetch refs for ${pageName}:`, e);
                    }
                });
                await Promise.all(promises);
            }

            const degreeCount = {};
            for (const edge of edges) {
                degreeCount[edge.source] = (degreeCount[edge.source] || 0) + 1;
                degreeCount[edge.target] = (degreeCount[edge.target] || 0) + 1;
            }

            const nodes = Array.from(nodesMap.values());
            for (const node of nodes) {
                node.degree = degreeCount[node.id] || 0;
            }

            const connectedNodes = nodes.filter(n => n.degree > 0 || n.hasPage);

            this.allNodes = connectedNodes;
            this.allEdges = edges;
            this.graphData = { nodes: connectedNodes, edges };
            this.communityCount = 0;
            this.communityLabels = [];

            this.render();
        } catch (err) {
            console.error('Failed to build graph:', err);
            document.getElementById('graph-container').innerHTML =
                '<div class="empty-state"><h2>Failed to load graph</h2><p>' + err.message + '</p></div>';
        }
    }

    renderAnalysisSummary() {
        if (!this.analysisData) return;

        const container = document.getElementById('graph-container');
        const summary = document.createElement('div');
        summary.className = 'analysis-summary';

        const centrality = this.analysisData.centrality || {};
        const communities = this.analysisData.communities || {};
        const suggestions = this.analysisData.suggestions || {};

        const topPages = (centrality.top_pages || []).slice(0, 3);
        const suggestedCount = (suggestions.suggested_pages || []).length;
        const bridgeCount = (communities.bridge_nodes || []).length;
        const communityCount = (communities.community_list || []).length;

        summary.innerHTML = `
            <div class="summary-row">
                <span class="summary-label">Communities:</span>
                <span class="summary-value">${communityCount}</span>
                <span class="summary-divider">|</span>
                <span class="summary-label">Bridge Nodes:</span>
                <span class="summary-value">${bridgeCount}</span>
                <span class="summary-divider">|</span>
                <span class="summary-label">Suggested Pages:</span>
                <span class="summary-value">${suggestedCount}</span>
            </div>
            ${topPages.length > 0 ? `
                <div class="summary-row">
                    <span class="summary-label">Top Hubs:</span>
                    <span class="summary-value">${topPages.map(p => p.page).join(', ')}</span>
                </div>
            ` : ''}
        `;

        container.appendChild(summary);
    }

    render() {
        const container = document.getElementById('graph-container');
        const existingSvg = container.querySelector('#graph-svg');
        const existingSummary = container.querySelector('.analysis-summary');
        if (existingSvg) existingSvg.remove();
        if (existingSummary) existingSummary.remove();

        const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svgEl.id = 'graph-svg';
        svgEl.setAttribute('width', '100%');
        svgEl.setAttribute('height', '600');
        container.insertBefore(svgEl, container.firstChild);

        const tooltip = document.getElementById('graph-tooltip');
        if (tooltip) tooltip.classList.add('hidden');

        const width = container.clientWidth;
        const height = 600;

        this.svg = d3.select(svgEl)
            .attr('viewBox', [0, 0, width, height]);

        this.svg.selectAll('*').remove();

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

        // Community color scale
        const communityColorScale = d3.scaleOrdinal()
            .domain(d3.range(0, this.communityCount || 2))
            .range(this.communityColors);

        // Node color function: community-based if available, else type-based
        const nodeColor = (d) => {
            if (d.type === 'suggested') return '#f9e2af';
            if (d.community >= 0 && this.communityCount > 0) {
                return communityColorScale(d.community);
            }
            return d.type === 'entity' ? '#a6e3a1' : '#89b4fa';
        };

        const g = this.svg.append('g');

        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => {
                g.attr('transform', event.transform);
            });

        this.svg.call(zoom);

        // Node radius based on PageRank score (or degree as fallback)
        const nodeRadius = (d) => {
            if (d.type === 'suggested') return 6;
            if (d.score > 0) {
                const maxScore = Math.max(...this.allNodes.map(n => n.score), 0.01);
                const normalized = d.score / maxScore;
                return Math.max(8, Math.min(22, 8 + normalized * 14));
            }
            return Math.max(6, Math.min(18, 6 + Math.sqrt(d.degree || 1) * 3));
        };

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

        const link = g.append('g')
            .selectAll('line')
            .data(this.graphData.edges)
            .join('line')
            .attr('stroke', d => d.type === 'wikilink' ? '#a6adc8' : '#6c7086')
            .attr('stroke-width', 1.5)
            .attr('stroke-dasharray', d => d.type === 'relation' ? '4,4' : null)
            .attr('marker-end', d => d.type === 'wikilink' ? 'url(#arrow-wikilink)' : 'url(#arrow-relation)');

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
            .attr('r', nodeRadius)
            .attr('fill', nodeColor)
            .attr('stroke', d => {
                if (d.type === 'suggested') return '#f9e2af';
                if (d.isBridge) return '#fab387';
                return d.hasPage ? '#4ade80' : 'transparent';
            })
            .attr('stroke-width', d => d.isBridge ? 3 : 2)
            .attr('stroke-dasharray', d => d.type === 'suggested' ? '3,3' : null)
            .attr('opacity', 0.9);

        // Node labels
        node.append('text')
            .text(d => d.label.length > 20 ? d.label.substring(0, 18) + '...' : d.label)
            .attr('x', d => nodeRadius(d) + 4)
            .attr('y', 4)
            .attr('font-size', '10px')
            .attr('fill', '#cdd6f4')
            .attr('pointer-events', 'none')
            .attr('text-shadow', '0 1px 3px rgba(0,0,0,0.8)');

        // Bridge node indicator
        node.filter(d => d.isBridge)
            .append('text')
            .text('⬡')
            .attr('x', -6)
            .attr('y', 4)
            .attr('font-size', '8px')
            .attr('fill', '#fab387')
            .attr('pointer-events', 'none');

        // Node interactions
        node.on('mouseover', (event, d) => {
            const tooltipEl = document.getElementById('graph-tooltip');
            tooltipEl.classList.remove('hidden');

            let extraInfo = '';
            if (d.score > 0) extraInfo += ` | PageRank: ${d.score.toFixed(4)}`;
            if (d.isBridge) extraInfo += ' | Bridge';
            if (d.type === 'suggested') extraInfo += ` | ${d.reason || ''}`;

            tooltipEl.innerHTML = `
                <div class="tooltip-title">${d.label}</div>
                <div class="tooltip-type">Community: ${d.communityLabel} | Degree: ${d.degree}${extraInfo}</div>
            `;
            tooltipEl.style.left = (event.pageX + 12) + 'px';
            tooltipEl.style.top = (event.pageY - 12) + 'px';

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

        this.simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

        this.simulation.alpha(1).restart();
    }

    setupInteractions() {
        const refreshBtn = document.getElementById('btn-graph-refresh');
        if (refreshBtn) {
            refreshBtn.onclick = () => this.loadData();
        }

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

        const filterBtn = document.getElementById('btn-graph-filter');
        if (filterBtn) {
            filterBtn.onclick = () => {
                this.isFiltered = !this.isFiltered;
                if (this.isFiltered) {
                    const filtered = this.graphData.nodes.filter(n => n.degree >= 2);
                    const filteredIds = new Set(filtered.map(n => n.id));

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

        const closeBtn = document.getElementById('btn-close-graph');
        if (closeBtn) {
            closeBtn.onclick = () => this.close();
        }

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
