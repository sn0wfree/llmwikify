/**
 * llmwikify Web UI - Main Application
 */

(function() {
    'use strict';

    // ============================================================
    // State
    // ============================================================
    const state = {
        currentPage: null,
        currentContent: '',
        viewMode: 'preview',
        fileTree: {},
        searchTimeout: null,
        hasUnsavedChanges: false,
        livePreviewTimeout: null,
    };

    // ============================================================
    // MCP API Client
    // ============================================================
    const api = {
        async call(method, params = {}) {
            try {
                const resp = await fetch('/api/rpc', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: Date.now(),
                        method,
                        params
                    })
                });
                
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
                }
                
                const { result, error } = await resp.json();
                
                if (error) {
                    throw new Error(error.message || 'MCP call failed');
                }
                
                if (typeof result === 'string') {
                    try {
                        return JSON.parse(result);
                    } catch {
                        return result;
                    }
                }
                return result;
            } catch (err) {
                console.error(`API call failed: ${method}`, err);
                throw err;
            }
        },

        async wiki_read_page(page_name) {
            return this.call('wiki_read_page', { page_name });
        },

        async wiki_write_page(page_name, content) {
            return this.call('wiki_write_page', { page_name, content });
        },

        async wiki_search(query, limit = 20) {
            return this.call('wiki_search', { query, limit });
        },

        async wiki_references(page_name, detail = true) {
            return this.call('wiki_references', { page_name, detail, inbound: false, outbound: false });
        },

        async wiki_status() {
            return this.call('wiki_status', {});
        },

        async wiki_lint(format = 'brief') {
            return this.call('wiki_lint', { format, generate_investigations: false });
        },

        async wiki_sink_status() {
            return this.call('wiki_sink_status', {});
        },

        async wiki_recommend() {
            return this.call('wiki_recommend', {});
        },

        async wiki_build_index() {
            return this.call('wiki_build_index', { auto_export: true });
        },

        async wiki_graph_analyze(action, params = {}) {
            return this.call('wiki_graph_analyze', { action, ...params });
        },

        async wiki_graph(action, params = {}) {
            return this.call('wiki_graph', { action, ...params });
        },

        async wiki_suggest_synthesis(source_name = null) {
            return this.call('wiki_suggest_synthesis', { source_name });
        },

        async wiki_knowledge_gaps(limit = 20) {
            return this.call('wiki_knowledge_gaps', { limit });
        },
    };

    // ============================================================
    // DOM Helpers
    // ============================================================
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function el(tag, attrs = {}, children = []) {
        const element = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs)) {
            if (key === 'className') {
                element.className = value;
            } else if (key === 'textContent') {
                element.textContent = value;
            } else if (key === 'onclick') {
                element.addEventListener('click', value);
            } else {
                element.setAttribute(key, value);
            }
        }
        for (const child of children) {
            if (typeof child === 'string') {
                element.appendChild(document.createTextNode(child));
            } else if (child) {
                element.appendChild(child);
            }
        }
        return element;
    }

    // ============================================================
    // Markdown Renderer
    // ============================================================
    function renderMarkdown(content) {
        marked.setOptions({ breaks: true, gfm: true });
        let html = marked.parse(content || '');

        html = html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (match, target, display) => {
            const linkText = display || target;
            const cleanTarget = target.split('#')[0].trim();
            return `<a href="#" class="wikilink" data-page="${cleanTarget}">${linkText}</a>`;
        });

        return html;
    }

    // ============================================================
    // File Tree
    // ============================================================
    function renderFileTree(status) {
        const treeEl = $('#file-tree');
        const pagesByType = status.pages_by_type || {};
        const groups = Object.entries(pagesByType).filter(([type, pages]) => pages.length > 0);
        
        if (groups.length === 0) {
            treeEl.innerHTML = '<div class="tree-empty">No pages yet</div>';
            return;
        }

        treeEl.innerHTML = '';
        
        for (const [type, pages] of groups) {
            const group = el('div', { className: 'tree-group' });
            
            const header = el('div', {
                className: 'tree-group-header',
                textContent: `${type} (${pages.length})`,
                onclick: () => group.classList.toggle('collapsed')
            });
            
            const items = el('div', { className: 'tree-group-items' });
            
            for (const pageName of pages.sort()) {
                const item = el('div', {
                    className: 'tree-item' + (state.currentPage === pageName ? ' active' : ''),
                    textContent: pageName,
                    onclick: () => loadPage(pageName)
                });
                items.appendChild(item);
            }
            
            group.appendChild(header);
            group.appendChild(items);
            treeEl.appendChild(group);
        }
    }

    // ============================================================
    // Page Loading
    // ============================================================
    async function loadPage(pageName) {
        try {
            showLoading();
            
            const page = await api.wiki_read_page(pageName);
            state.currentPage = pageName;
            state.currentContent = page.content || '';
            state.hasUnsavedChanges = false;
            updateUnsavedIndicator();
            updatePageTitle(pageName);
            
            $('#preview-content').innerHTML = renderMarkdown(state.currentContent);
            $('#editor').value = state.currentContent;
            
            $$('.tree-item').forEach(item => {
                item.classList.toggle('active', item.textContent === pageName);
            });
            
            loadBacklinks(pageName);
            
        } catch (err) {
            $('#preview-content').innerHTML = `
                <div class="empty-state">
                    <h2>Error loading page</h2>
                    <p>${err.message}</p>
                </div>
            `;
        }
    }

    function updatePageTitle(name) {
        const el = $('#current-page-name');
        if (el) el.textContent = name || 'Home';
    }

    function updateUnsavedIndicator() {
        const dot = $('#unsaved-dot');
        if (dot) dot.style.display = state.hasUnsavedChanges ? 'inline-block' : 'none';
    }

    async function loadBacklinks(pageName) {
        try {
            const refs = await api.wiki_references(pageName);
            
            const backlinksEl = $('#backlinks-list');
            const inbound = refs.inbound || [];
            
            if (inbound.length === 0) {
                backlinksEl.innerHTML = '<div class="tree-empty">None</div>';
            } else {
                backlinksEl.innerHTML = '';
                for (const link of inbound) {
                    const item = el('div', {
                        className: 'link-item',
                        onclick: () => loadPage(link.source_page || link.source)
                    });
                    item.appendChild(document.createTextNode(link.source_page || link.source));
                    if (link.context) {
                        item.appendChild(el('span', {
                            className: 'context',
                            textContent: link.context.substring(0, 80) + '...'
                        }));
                    }
                    backlinksEl.appendChild(item);
                }
            }
            
            const outgoingEl = $('#outgoing-list');
            const outbound = refs.outbound || [];
            
            if (outbound.length === 0) {
                outgoingEl.innerHTML = '<div class="tree-empty">None</div>';
            } else {
                outgoingEl.innerHTML = '';
                for (const link of outbound) {
                    const item = el('div', {
                        className: 'link-item',
                        onclick: () => loadPage(link.target_page || link.target)
                    });
                    item.appendChild(document.createTextNode(link.target_page || link.target));
                    outgoingEl.appendChild(item);
                }
            }
            
        } catch (err) {
            console.error('Failed to load backlinks:', err);
        }
    }

    // ============================================================
    // Search
    // ============================================================
    function initSearch() {
        const input = $('#search-input');
        const results = $('#search-results');
        
        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (state.searchTimeout) clearTimeout(state.searchTimeout);
            
            if (query.length < 2) {
                results.classList.add('hidden');
                return;
            }
            
            state.searchTimeout = setTimeout(async () => {
                try {
                    const results_data = await api.wiki_search(query, 15);
                    renderSearchResults(results_data, results);
                } catch (err) {
                    results.innerHTML = '<div class="search-empty">Search failed</div>';
                    results.classList.remove('hidden');
                }
            }, 300);
        });
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                input.value = '';
                results.classList.add('hidden');
            }
        });
        
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-box')) {
                results.classList.add('hidden');
            }
        });
    }

    function renderSearchResults(results, container) {
        if (!results || results.length === 0) {
            container.innerHTML = '<div class="search-empty">No results</div>';
            container.classList.remove('hidden');
            return;
        }
        
        container.innerHTML = '';
        
        for (const result of results) {
            const item = el('div', {
                className: 'search-item',
                onclick: () => {
                    loadPage(result.page_name);
                    container.classList.add('hidden');
                    $('#search-input').value = '';
                }
            });
            
            const title = el('div', { className: 'title', textContent: result.page_name });
            const snippet = el('div', { className: 'snippet', innerHTML: result.snippet || '' });
            
            item.appendChild(title);
            item.appendChild(snippet);
            container.appendChild(item);
        }
        
        container.classList.remove('hidden');
    }

    // ============================================================
    // Editor
    // ============================================================
    function initEditor() {
        const editor = $('#editor');
        
        // Save on Ctrl+S
        editor.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                savePage();
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
                e.preventDefault();
                wrapSelection('**', '**');
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
                e.preventDefault();
                wrapSelection('*', '*');
            }
        });

        // Track unsaved changes
        editor.addEventListener('input', () => {
            if (editor.value !== state.currentContent) {
                state.hasUnsavedChanges = true;
                updateUnsavedIndicator();
            }

            // Live preview in split mode
            if (state.viewMode === 'split') {
                if (state.livePreviewTimeout) clearTimeout(state.livePreviewTimeout);
                state.livePreviewTimeout = setTimeout(() => {
                    $('#preview-content').innerHTML = renderMarkdown(editor.value);
                    rebindWikilinks();
                }, 200);
            }
        });
    }

    function wrapSelection(before, after) {
        const editor = $('#editor');
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const text = editor.value;
        const selected = text.substring(start, end);
        
        editor.value = text.substring(0, start) + before + selected + after + text.substring(end);
        editor.focus();
        editor.selectionStart = start + before.length;
        editor.selectionEnd = start + before.length + selected.length;
        
        // Trigger input event for live preview
        editor.dispatchEvent(new Event('input'));
    }

    function initEditorToolbar() {
        $$('#editor-toolbar button').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.cmd;
                switch (cmd) {
                    case 'bold': wrapSelection('**', '**'); break;
                    case 'italic': wrapSelection('*', '*'); break;
                    case 'code': wrapSelection('`', '`'); break;
                    case 'codeblock': wrapSelection('\n```\n', '\n```\n'); break;
                    case 'link': wrapSelection('[[', ']]'); break;
                    case 'heading': wrapSelection('\n# ', '\n'); break;
                    case 'list': wrapSelection('\n- ', '\n'); break;
                    case 'table': insertTable(); break;
                }
            });
        });
    }

    function insertTable() {
        const table = '\n| Header 1 | Header 2 | Header 3 |\n|----------|----------|----------|\n| Cell 1   | Cell 2   | Cell 3   |\n| Cell 4   | Cell 5   | Cell 6   |\n';
        const editor = $('#editor');
        const start = editor.selectionStart;
        editor.value = editor.value.substring(0, start) + table + editor.value.substring(start);
        editor.dispatchEvent(new Event('input'));
    }

    async function savePage() {
        if (!state.currentPage) return;
        
        const content = $('#editor').value;
        try {
            await api.wiki_write_page(state.currentPage, content);
            state.currentContent = content;
            state.hasUnsavedChanges = false;
            updateUnsavedIndicator();
            $('#preview-content').innerHTML = renderMarkdown(content);
            showToast('Page saved');
        } catch (err) {
            showToast(`Save failed: ${err.message}`, true);
        }
    }

    // ============================================================
    // View Modes
    // ============================================================
    function initViewTabs() {
        $$('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const mode = tab.dataset.view;
                setViewMode(mode);
                $$('.tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
            });
        });
    }

    function setViewMode(mode) {
        state.viewMode = mode;
        const preview = $('#preview-pane');
        const edit = $('#edit-pane');
        const content = $('#content');
        
        content.classList.toggle('split-view', mode === 'split');
        
        if (mode === 'preview') {
            preview.classList.remove('hidden');
            edit.classList.add('hidden');
        } else if (mode === 'edit') {
            preview.classList.add('hidden');
            edit.classList.remove('hidden');
        } else if (mode === 'split') {
            preview.classList.remove('hidden');
            edit.classList.remove('hidden');
            // Initial render for split mode
            $('#preview-content').innerHTML = renderMarkdown($('#editor').value);
            rebindWikilinks();
        }
    }

    function rebindWikilinks() {
        // Wikilinks are handled by event delegation on #preview-content
    }

    // ============================================================
    // New Page Modal
    // ============================================================
    function initNewPageModal() {
        const modal = $('#new-page-modal');
        const input = $('#new-page-name');
        
        $('#btn-new').addEventListener('click', () => {
            modal.classList.remove('hidden');
            input.value = '';
            input.focus();
        });
        
        $('#btn-close-new').addEventListener('click', () => modal.classList.add('hidden'));
        $('#btn-cancel-new').addEventListener('click', () => modal.classList.add('hidden'));
        $('#btn-create-page').addEventListener('click', createNewPage);
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') createNewPage();
            else if (e.key === 'Escape') modal.classList.add('hidden');
        });
    }

    async function createNewPage() {
        const name = $('#new-page-name').value.trim();
        if (!name) return;
        
        try {
            await api.wiki_write_page(name, `# ${name}\n\n`);
            $('#new-page-modal').classList.add('hidden');
            loadPage(name);
            refreshTree();
            showToast('Page created');
        } catch (err) {
            showToast(`Failed to create: ${err.message}`, true);
        }
    }

    // ============================================================
    // Graph View
    // ============================================================
    function initGraphView() {
        const graphView = new GraphView(api, loadPage);
        
        $('#btn-graph').addEventListener('click', () => graphView.open());
        $('#btn-close-graph').addEventListener('click', () => graphView.close());
        
        document.getElementById('graph-modal').addEventListener('click', (e) => {
            if (e.target.id === 'graph-modal') graphView.close();
        });
    }

    // ============================================================
    // Wikilink Navigation
    // ============================================================
    function initWikilinks() {
        $('#preview-content').addEventListener('click', (e) => {
            const link = e.target.closest('.wikilink');
            if (link) {
                e.preventDefault();
                const pageName = link.dataset.page;
                if (pageName) loadPage(pageName);
            }
        });
    }

    // ============================================================
    // Sidebar Panels (Health/Sink/Recommendations)
    // ============================================================
    async function loadSidebarPanels() {
        // Health
        try {
            const lint = await api.wiki_lint('brief');
            const hints = lint.hints || {};
            const issues = lint.issue_count || 0;

            const brokenCount = hints.broken_links ? Object.keys(hints.broken_links).length : 0;

            $('#health-broken-dot').className = 'health-dot ' + (brokenCount > 0 ? 'dot-danger' : 'dot-ok');
            $('#health-broken-text').textContent = brokenCount > 0 ? `${brokenCount} broken` : 'OK';

            const orphanPages = lint.orphan_pages || hints.orphan_pages || [];
            $('#health-orphans-dot').className = 'health-dot ' + (orphanPages.length > 0 ? 'dot-warning' : 'dot-ok');
            $('#health-orphans-text').textContent = orphanPages.length > 0 ? `${orphanPages.length} orphans` : 'OK';
        } catch (e) {
            $('#health-broken-text').textContent = 'N/A';
            $('#health-orphans-text').textContent = 'N/A';
        }

        // Stale pages + Knowledge gaps (light check)
        try {
            const fullLint = await api.wiki_knowledge_gaps(5);
            const investigations = fullLint.investigations || {};

            const outdated = investigations.outdated_pages || [];
            const gaps = investigations.knowledge_gaps || [];

            $('#health-stale-dot').className = 'health-dot ' + (outdated.length > 0 ? 'dot-warning' : 'dot-ok');
            $('#health-stale-text').textContent = outdated.length > 0 ? `${outdated.length} stale` : 'OK';
        } catch (e) {
            $('#health-stale-text').textContent = 'N/A';
        }

        // Sink Status
        try {
            const sink = await api.wiki_sink_status();
            const sinks = Array.isArray(sink) ? sink : (sink.sinks || []);
            const totalPending = sinks.reduce((sum, s) => sum + (s.entry_count || 0), 0);
            
            const sinkEl = $('#sink-status');
            if (totalPending > 0) {
                const urgent = sinks.filter(s => s.urgency === 'urgent' || s.urgency === 'aging');
                sinkEl.innerHTML = urgent.length > 0
                    ? `<span class="sink-item sink-urgent">${urgent.length} urgent updates</span>`
                    : `<span class="sink-item">${totalPending} pending</span>`;
            } else {
                sinkEl.innerHTML = '<span class="sink-item">No pending updates</span>';
            }
        } catch (e) {
            $('#sink-status').innerHTML = '<span class="sink-item">N/A</span>';
        }

        // Recommendations
        try {
            const rec = await api.wiki_recommend();
            const missing = rec.missing_pages || [];
            
            const recEl = $('#recommendations');
            if (missing.length > 0) {
                recEl.innerHTML = '';
                for (const page of missing.slice(0, 5)) {
                    const item = el('span', {
                        className: 'rec-item',
                        textContent: page,
                        onclick: () => createNewPageByName(page)
                    });
                    recEl.appendChild(item);
                }
            } else {
                recEl.innerHTML = '<span class="rec-item">No recommendations</span>';
            }
        } catch (e) {
            $('#recommendations').innerHTML = '<span class="rec-item">N/A</span>';
        }
    }

    async function createNewPageByName(name) {
        try {
            await api.wiki_write_page(name, `# ${name}\n\n`);
            loadPage(name);
            refreshTree();
            showToast('Page created: ' + name);
        } catch (err) {
            showToast(`Failed: ${err.message}`, true);
        }
    }

    // ============================================================
    // Insights Panel (P1: Synthesis, Gaps, Graph Analysis)
    // ============================================================
    function initInsightsPanel() {
        // Tab switching
        $$('.insight-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                $$('.insight-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                $$('.insight-content').forEach(c => c.classList.add('hidden'));
                const content = document.getElementById(`insight-${tabName}`);
                if (content) content.classList.remove('hidden');
            });
        });

        // Load synthesis
        $('#insight-synthesis').addEventListener('click', async function handler() {
            if (this.dataset.loaded) return;
            await loadSynthesisInsights();
            this.dataset.loaded = 'true';
            this.removeEventListener('click', handler);
        });

        // Load gaps
        $('#insight-gaps').addEventListener('click', async function handler() {
            if (this.dataset.loaded) return;
            await loadGapsInsights();
            this.dataset.loaded = 'true';
            this.removeEventListener('click', handler);
        });

        // Load graph analysis
        $('#insight-graph').addEventListener('click', async function handler() {
            if (this.dataset.loaded) return;
            await loadGraphInsights();
            this.dataset.loaded = 'true';
            this.removeEventListener('click', handler);
        });

        // Refresh button
        const refreshBtn = $('#btn-refresh-insights');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                ['insight-synthesis', 'insight-gaps', 'insight-graph'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.dataset.loaded = '';
                        el.innerHTML = '<div class="insight-loading">Click to analyze</div>';
                    }
                });
            });
        }
    }

    async function loadSynthesisInsights() {
        const container = $('#insight-synthesis');
        container.innerHTML = '<div class="insight-loading">Analyzing sources...</div>';

        try {
            const result = await api.wiki_suggest_synthesis();
            const suggestions = result.suggestions || [];

            if (suggestions.length === 0) {
                container.innerHTML = '<div class="insight-empty">No sources to analyze</div>';
                return;
            }

            container.innerHTML = '';
            for (const sugg of suggestions) {
                const reinforced = sugg.reinforced_claims || [];
                const gaps = sugg.knowledge_gaps || [];
                const updates = sugg.suggested_updates || [];

                if (reinforced.length === 0 && gaps.length === 0 && updates.length === 0) continue;

                const item = el('div', { className: 'insight-item' });
                const title = el('div', {
                    className: 'insight-title',
                    textContent: `${reinforced.length} reinforced, ${gaps.length} gaps, ${updates.length} updates`
                });
                item.appendChild(title);

                for (const claim of reinforced.slice(0, 2)) {
                    const desc = el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-reinforced">reinforced</span> ${claim.claim || claim.text || ''}`.substring(0, 100)
                    });
                    item.appendChild(desc);
                }

                for (const gap of gaps.slice(0, 2)) {
                    const desc = el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-gap">gap</span> ${gap.gap || ''}`.substring(0, 100)
                    });
                    item.appendChild(desc);
                }

                container.appendChild(item);
            }

            if (container.children.length === 0) {
                container.innerHTML = '<div class="insight-empty">No synthesis suggestions</div>';
            }
        } catch (e) {
            container.innerHTML = `<div class="insight-empty">Failed: ${e.message}</div>`;
        }
    }

    async function loadGapsInsights() {
        const container = $('#insight-gaps');
        container.innerHTML = '<div class="insight-loading">Detecting gaps...</div>';

        try {
            const result = await api.wiki_knowledge_gaps(10);
            const investigations = result.investigations || {};

            const outdated = investigations.outdated_pages || [];
            const gaps = investigations.knowledge_gaps || [];
            const redundant = investigations.redundant_pages || [];

            container.innerHTML = '';

            if (outdated.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: `${outdated.length} outdated page(s)`
                }));
                for (const page of outdated.slice(0, 3)) {
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-medium">outdated</span> ${page.page}`
                    }));
                }
                container.appendChild(item);
            }

            if (gaps.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: `${gaps.length} knowledge gap(s)`
                }));
                for (const gap of gaps.slice(0, 3)) {
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-info">gap</span> ${gap.gap || gap}`.substring(0, 80)
                    }));
                }
                container.appendChild(item);
            }

            if (redundant.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: `${redundant.length} potentially redundant page(s)`
                }));
                for (const pair of redundant.slice(0, 2)) {
                    const pages = pair.pages || pair;
                    const desc = Array.isArray(pages) ? pages.join(' ↔ ') : pages;
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-low">redundant</span> ${desc}`
                    }));
                }
                container.appendChild(item);
            }

            if (container.children.length === 0) {
                container.innerHTML = '<div class="insight-empty">No gaps detected</div>';
            }
        } catch (e) {
            container.innerHTML = `<div class="insight-empty">Failed: ${e.message}</div>`;
        }
    }

    async function loadGraphInsights() {
        const container = $('#insight-graph');
        container.innerHTML = '<div class="insight-loading">Analyzing graph...</div>';

        try {
            const result = await api.wiki_graph_analyze('analyze');
            const suggestions = result.suggestions || {};
            const centrality = result.centrality || {};
            const communities = result.communities || {};

            container.innerHTML = '';

            // Suggested pages
            const suggestedPages = suggestions.suggested_pages || [];
            if (suggestedPages.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: `${suggestedPages.length} suggested page(s)`
                }));
                for (const sugg of suggestedPages.slice(0, 4)) {
                    const reason = sugg.reason || 'Orphan concept';
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-medium">suggest</span> ${sugg.page_name || sugg.page}`
                    }));
                    item.appendChild(el('div', {
                        className: 'insight-meta',
                        textContent: reason.substring(0, 70)
                    }));
                }
                container.appendChild(item);
            }

            // Bridge nodes
            const bridges = communities.bridge_nodes || [];
            if (bridges.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: `${bridges.length} bridge node(s)`
                }));
                for (const bridge of bridges.slice(0, 3)) {
                    const nodeName = bridge.node || bridge;
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-info">bridge</span> ${nodeName}`
                    }));
                }
                container.appendChild(item);
            }

            // Top hubs
            const topPages = centrality.top_pages || [];
            if (topPages.length > 0) {
                const item = el('div', { className: 'insight-item' });
                item.appendChild(el('div', {
                    className: 'insight-title',
                    textContent: 'Top hubs (PageRank)'
                }));
                for (const entry of topPages.slice(0, 3)) {
                    item.appendChild(el('div', {
                        className: 'insight-desc',
                        innerHTML: `<span class="insight-badge badge-low">hub</span> ${entry.page} (${entry.score.toFixed(3)})`
                    }));
                }
                container.appendChild(item);
            }

            if (container.children.length === 0) {
                container.innerHTML = '<div class="insight-empty">No graph insights</div>';
            }
        } catch (e) {
            container.innerHTML = `<div class="insight-empty">Failed: ${e.message}</div>`;
        }
    }

    // ============================================================
    // Utilities
    // ============================================================
    function showLoading() {
        $('#preview-content').innerHTML = '<div class="loading">Loading</div>';
    }

    function showToast(message, isError = false) {
        const toast = el('div', {
            className: 'status-bar',
            style: `position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); 
                    background: ${isError ? 'var(--danger)' : 'var(--accent)'}; 
                    color: ${isError ? '#fff' : 'var(--bg-primary)'};
                    padding: 8px 16px; border-radius: 8px; z-index: 1000;
                    font-size: 13px; font-weight: 500;`
        }, [], [document.createTextNode(message)]);
        
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);
    }

    async function refreshTree() {
        try {
            const status = await api.wiki_status();
            renderFileTree(status);
        } catch (err) {
            console.error('Failed to refresh tree:', err);
        }
    }

    // ============================================================
    // Initialization
    // ============================================================
    async function init() {
        try {
            await refreshTree();
            await loadSidebarPanels();
            initSearch();
            initViewTabs();
            initEditor();
            initEditorToolbar();
            initNewPageModal();
            initWikilinks();
            initGraphView();
            initInsightsPanel();
            
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                    e.preventDefault();
                    $('#search-input').focus();
                    $('#search-input').select();
                }
            });
            
            console.log('llmwikify Web UI initialized (Phase 2)');
        } catch (err) {
            console.error('Failed to initialize:', err);
            $('#preview-content').innerHTML = `
                <div class="empty-state">
                    <h2>Failed to connect</h2>
                    <p>Make sure the MCP server is running.</p>
                    <p style="margin-top: 8px; font-size: 12px;">${err.message}</p>
                </div>
            `;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
