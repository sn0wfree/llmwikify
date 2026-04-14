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
        viewMode: 'preview',  // 'preview' | 'edit' | 'split'
        fileTree: {},
        searchTimeout: null,
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
                
                // MCP tools return JSON strings
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
        // Configure marked
        marked.setOptions({
            breaks: true,
            gfm: true,
        });

        let html = marked.parse(content || '');

        // Convert [[wikilinks]] to clickable elements
        html = html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (match, target, display) => {
            const linkText = display || target;
            // Remove section anchors for link text
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
            
            // Update preview
            $('#preview-content').innerHTML = renderMarkdown(state.currentContent);
            
            // Update editor
            $('#editor').value = state.currentContent;
            
            // Update tree selection
            $$('.tree-item').forEach(item => {
                item.classList.toggle('active', item.textContent === pageName);
            });
            
            // Load backlinks
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

    async function loadBacklinks(pageName) {
        try {
            const refs = await api.wiki_references(pageName);
            
            // Backlinks
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
            
            // Outgoing
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
            
            if (state.searchTimeout) {
                clearTimeout(state.searchTimeout);
            }
            
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
        
        // Close results when clicking outside
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
            
            const title = el('div', {
                className: 'title',
                textContent: result.page_name
            });
            
            const snippet = el('div', {
                className: 'snippet',
                innerHTML: result.snippet || ''
            });
            
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
        });
    }

    async function savePage() {
        if (!state.currentPage) return;
        
        const content = $('#editor').value;
        try {
            await api.wiki_write_page(state.currentPage, content);
            state.currentContent = content;
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
        }
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
        
        $('#btn-close-new').addEventListener('click', () => {
            modal.classList.add('hidden');
        });
        
        $('#btn-cancel-new').addEventListener('click', () => {
            modal.classList.add('hidden');
        });
        
        $('#btn-create-page').addEventListener('click', createNewPage);
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                createNewPage();
            } else if (e.key === 'Escape') {
                modal.classList.add('hidden');
            }
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
    // Wikilink Navigation
    // ============================================================
    function initWikilinks() {
        $('#preview-content').addEventListener('click', (e) => {
            const link = e.target.closest('.wikilink');
            if (link) {
                e.preventDefault();
                const pageName = link.dataset.page;
                if (pageName) {
                    loadPage(pageName);
                }
            }
        });
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
            initSearch();
            initViewTabs();
            initEditor();
            initNewPageModal();
            initWikilinks();
            
            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Ctrl+K: focus search
                if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                    e.preventDefault();
                    $('#search-input').focus();
                    $('#search-input').select();
                }
            });
            
            console.log('llmwikify Web UI initialized');
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

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
