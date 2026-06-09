import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Group, Panel, Separator } from 'react-resizable-panels';
import {
  Save, FileText, Network, Eye, PanelLeftClose, PanelLeftOpen,
  Check, AlertCircle, Loader2, Pencil, Hash,
} from 'lucide-react';
import { api, WikiPage, GraphNode, GraphEdge } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { useToast } from './Toast';
import { EmptyState, LoadingState } from '../ui/states';
import { FrontMatterPanel, FrontMatterData } from './FrontMatterPanel';
import { GraphView } from './GraphView';
import { PageTree } from './PageTree';
import { cn } from '@/lib/utils';

interface EditorProps {
  selectedPage?: string | null;
  handlePageSelect?: (page: string) => void;
  currentWikiId?: string | null;
}

type ViewMode = 'edit' | 'graph' | 'preview';

function parseFrontMatter(content: string): { metadata: FrontMatterData; body: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) return { metadata: {}, body: content };

  const metadata: FrontMatterData = {};
  match[1].split('\n').forEach((line) => {
    const colonIndex = line.indexOf(':');
    if (colonIndex === -1) return;
    const key = line.slice(0, colonIndex).trim();
    let value: string | string[] = line.slice(colonIndex + 1).trim();
    if (value.startsWith('[') && value.endsWith(']')) {
      value = value.slice(1, -1).split(',').map((s) => s.trim());
    }
    metadata[key] = value;
  });

  return { metadata, body: match[2].trim() };
}

function buildFrontMatter(metadata: FrontMatterData, body: string): string {
  if (Object.keys(metadata).length === 0) return body;
  const yaml = Object.entries(metadata)
    .map(([key, value]) => {
      if (Array.isArray(value)) return `${key}: [${value.join(', ')}]`;
      return `${key}: ${value}`;
    })
    .join('\n');
  return `---\n${yaml}\n---\n\n${body}`;
}

export function Editor({
  selectedPage: initialPage, handlePageSelect: externalOnSelect, currentWikiId,
}: EditorProps) {
  const { addToast } = useToast();
  const { isMultiWikiMode } = useWikiStore();
  const [internalSelectedPage, setInternalSelectedPage] = useState<string | null>(initialPage || null);
  const [page, setPage] = useState<WikiPage | null>(null);
  const [content, setContent] = useState('');
  const [metadata, setMetadata] = useState<FrontMatterData>({});
  const [body, setBody] = useState('');
  const [mode, setMode] = useState<ViewMode>('edit');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [pagesByType, setPagesByType] = useState<Record<string, string[]>>({});
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [allTypes, setAllTypes] = useState<string[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [showLabels, setShowLabels] = useState(true);

  const selectedPage = internalSelectedPage;

  const handlePageSelect = useCallback((pageName: string) => {
    if (dirty) {
      const ok = window.confirm('You have unsaved changes. Discard and switch?');
      if (!ok) return;
    }
    setInternalSelectedPage(pageName);
    setDirty(false);
    externalOnSelect?.(pageName);
  }, [externalOnSelect, dirty]);

  useEffect(() => { loadTree(); }, []);

  useEffect(() => {
    if (selectedPage) {
      loadPage(selectedPage, currentWikiId || undefined);
      loadGraphData(selectedPage, currentWikiId || undefined);
    } else {
      setPage(null);
      setContent('');
      setMetadata({});
      setBody('');
    }
  }, [selectedPage, currentWikiId]);

  useEffect(() => {
    if (currentWikiId) loadTree(currentWikiId);
  }, [currentWikiId]);

  const loadGraphData = useCallback(async (currentPage: string, wikiId?: string) => {
    setGraphLoading(true);
    try {
      let data;
      if (isMultiWikiMode && wikiId) {
        data = await api.wiki.scoped.graph(wikiId, currentPage);
      } else {
        data = await api.wiki.graph(currentPage);
      }
      setGraphNodes(data.nodes || []);
      setGraphEdges(data.edges || []);
      if (data.all_types) setAllTypes(data.all_types);
    } catch {
      setGraphNodes([]);
      setGraphEdges([]);
    } finally {
      setGraphLoading(false);
    }
  }, [isMultiWikiMode]);

  const loadTree = useCallback(async (wikiId?: string) => {
    try {
      let status;
      if (isMultiWikiMode && wikiId) {
        status = await api.wiki.scoped.status(wikiId);
      } else {
        status = await api.wiki.status();
      }
      setPagesByType(status.pages_by_type || {});
    } catch {
      addToast('warning', 'Could not load page tree');
    }
  }, [addToast, isMultiWikiMode]);

  const loadPage = useCallback(async (name: string, wikiId?: string) => {
    try {
      let data;
      if (isMultiWikiMode && wikiId) {
        data = await api.wiki.scoped.readPage(wikiId, name);
      } else {
        data = await api.wiki.readPage(name);
      }
      setPage(data);
      setContent(data.content);
      const { metadata: fm, body: b } = parseFrontMatter(data.content);
      setMetadata(fm);
      setBody(b);
      setDirty(false);
      setSavedAt(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      addToast('error', `Failed to load page: ${msg}`);
      setPage(null);
      setContent('');
      setMetadata({});
      setBody('');
    }
  }, [addToast, isMultiWikiMode]);

  const handleBodyChange = useCallback((newBody: string) => {
    setBody(newBody);
    setContent(buildFrontMatter(metadata, newBody));
    setDirty(true);
  }, [metadata]);

  const savePage = useCallback(async () => {
    if (!page) return;
    setSaving(true);
    try {
      if (isMultiWikiMode && currentWikiId) {
        await api.wiki.scoped.writePage(currentWikiId, page.page_name, content);
      } else {
        await api.wiki.writePage(page.page_name, content);
      }
      addToast('success', 'Page saved');
      setDirty(false);
      setSavedAt(Date.now());
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      addToast('error', `Save failed: ${msg}`);
    } finally {
      setSaving(false);
    }
  }, [page, content, addToast, isMultiWikiMode, currentWikiId]);

  // ⌘S / Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (page && dirty && !saving) savePage();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [page, dirty, saving, savePage]);

  const hasMetadata = Object.keys(metadata).length > 0;

  return (
    <div className="flex h-full">
      {/* File Tree Sidebar */}
      <div
        className={cn(
          'border-r border-border/50 overflow-y-auto shrink-0',
          'transition-[width] duration-200 ease-out',
        )}
        style={{ width: sidebarCollapsed ? 44 : 220 }}
      >
        {sidebarCollapsed ? (
          <div className="flex flex-col items-center py-2">
            <button
              onClick={() => setSidebarCollapsed(false)}
              className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
              title="Expand sidebar"
              aria-label="Expand sidebar"
            >
              <PanelLeftOpen className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <>
            <div className="px-2 py-2 flex items-center justify-between">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-1.5">
                Pages
              </span>
              <button
                onClick={() => setSidebarCollapsed(true)}
                className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-colors"
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
              >
                <PanelLeftClose className="w-3.5 h-3.5" />
              </button>
            </div>
            <PageTree
              pagesByType={pagesByType}
              selectedPage={page?.page_name || null}
              onSelect={handlePageSelect}
            />
          </>
        )}
      </div>

      {/* Editor Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="h-12 px-3 border-b border-border/50 flex items-center gap-2 shrink-0 glass" style={{ background: 'color-mix(in srgb, var(--background) 80%, transparent)' }}>
          {page ? (
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <span className="text-sm text-foreground font-medium truncate">{page.page_name}</span>
              {dirty && (
                <span className="text-[10px] text-warning font-medium shrink-0">●</span>
              )}
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">No page selected</span>
          )}

          <div className="flex items-center gap-1 ml-auto">
            {/* Mode toggle */}
            <div className="inline-flex p-0.5 rounded-md bg-white/[0.04] border border-border/40">
              {(['edit', 'graph', 'preview'] as const).map((m) => {
                const Icon = m === 'edit' ? Pencil : m === 'graph' ? Network : Eye;
                return (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    disabled={!page && m !== 'edit'}
                    className={cn(
                      'flex items-center gap-1 px-2 py-1 text-xs font-medium rounded transition-colors',
                      mode === m
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground disabled:opacity-40',
                    )}
                  >
                    <Icon className="w-3 h-3" />
                    <span className="hidden md:inline">{m === 'edit' ? 'Edit' : m === 'graph' ? 'Graph' : 'Preview'}</span>
                  </button>
                );
              })}
            </div>

            {/* Save button */}
            <button
              onClick={savePage}
              disabled={!page || saving || !dirty}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md transition-all',
                'shadow-soft',
                !page || !dirty
                  ? 'bg-white/[0.04] text-muted-foreground cursor-not-allowed'
                  : 'bg-gradient-to-br from-primary to-accent text-primary-foreground hover:brightness-110 hover:shadow-glow',
                saving && 'opacity-60',
              )}
              title="Save (⌘S)"
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : savedAt && !dirty ? (
                <Check className="w-3.5 h-3.5" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              <span className="hidden sm:inline">
                {saving ? 'Saving' : savedAt && !dirty ? 'Saved' : 'Save'}
              </span>
            </button>
          </div>
        </div>

        {/* Front Matter Panel */}
        {hasMetadata && <FrontMatterPanel metadata={metadata} />}

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {!page ? (
            <EmptyState
              icon={<FileText className="w-6 h-6" />}
              title="No page selected"
              description="Pick a page from the sidebar to start editing, or create a new one."
            />
          ) : mode === 'edit' ? (
            <Group direction="horizontal" className="h-full">
              <Panel defaultSize={50} minSize={25} className="overflow-hidden">
                <textarea
                  value={body}
                  onChange={(e) => handleBodyChange(e.target.value)}
                  className="w-full h-full bg-background text-foreground p-4 font-mono text-sm resize-none focus:outline-none border-0"
                  placeholder="Start writing markdown..."
                />
              </Panel>
              <Separator className="w-1 bg-border/40 hover:bg-primary/60 transition-colors cursor-col-resize" />
              <Panel defaultSize={50} minSize={25} className="overflow-hidden">
                <div className="w-full h-full overflow-y-auto p-4 markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {body || '*No content*'}
                  </ReactMarkdown>
                </div>
              </Panel>
            </Group>
          ) : mode === 'preview' ? (
            <div className="w-full h-full overflow-y-auto p-6 markdown-body max-w-3xl mx-auto">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {body || '*No content*'}
              </ReactMarkdown>
            </div>
          ) : (
            <Group direction="horizontal" className="h-full">
              <Panel defaultSize={60} minSize={30} className="overflow-hidden relative">
                <div className="absolute inset-0">
                  <GraphView
                    nodes={graphNodes}
                    edges={graphEdges}
                    allTypes={allTypes}
                    currentNode={page?.page_name || null}
                    onNodeClick={(nodeId) => handlePageSelect(nodeId)}
                    showLabels={showLabels}
                    isLoading={graphLoading}
                  />
                </div>
              </Panel>
              <Separator className="w-1 bg-border/40 hover:bg-primary/60 transition-colors cursor-col-resize" />
              <Panel defaultSize={40} minSize={20} className="overflow-hidden">
                <div className="w-full h-full overflow-y-auto p-4 markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {body || '*No content*'}
                  </ReactMarkdown>
                </div>
              </Panel>
            </Group>
          )}
        </div>
      </div>
    </div>
  );
}
