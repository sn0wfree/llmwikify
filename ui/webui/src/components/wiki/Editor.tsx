import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, WikiPage, GraphNode, GraphEdge } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { useToast } from './Toast';
import { FrontMatterPanel, FrontMatterData } from './FrontMatterPanel';
import { GraphView } from './GraphView';
import { PageTree } from './PageTree';
import { Button } from '../ui/Button';
import { cn } from '@/lib/utils';

interface EditorProps {
  selectedPage?: string | null;
  handlePageSelect?: (page: string) => void;
  currentWikiId?: string | null;
}

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
      if (Array.isArray(value)) {
        return `${key}: [${value.join(', ')}]`;
      }
      return `${key}: ${value}`;
    })
    .join('\n');

  return `---\n${yaml}\n---\n\n${body}`;
}

export function Editor({ selectedPage: initialPage, handlePageSelect: externalOnSelect, currentWikiId }: EditorProps) {
  const { addToast } = useToast();
  const { isMultiWikiMode } = useWikiStore();
  const [internalSelectedPage, setInternalSelectedPage] = useState<string | null>(initialPage || null);
  const [page, setPage] = useState<WikiPage | null>(null);
  const [content, setContent] = useState('');
  const [metadata, setMetadata] = useState<FrontMatterData>({});
  const [body, setBody] = useState('');
  const [mode, setMode] = useState<'edit' | 'graph'>('graph');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pagesByType, setPagesByType] = useState<Record<string, string[]>>({});
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [allTypes, setAllTypes] = useState<string[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [showLabels, setShowLabels] = useState(true);

  const selectedPage = internalSelectedPage;

  const handlePageSelect = useCallback((pageName: string) => {
    setInternalSelectedPage(pageName);
    externalOnSelect?.(pageName);
  }, [externalOnSelect]);

  useEffect(() => { loadTree(); }, []);

  useEffect(() => {
    if (selectedPage) {
      loadPage(selectedPage, currentWikiId || undefined);
      loadGraphData(selectedPage, currentWikiId || undefined);
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
      setGraphNodes(data.nodes);
      setGraphEdges(data.edges);
      if (data.all_types) setAllTypes(data.all_types);
    } catch {
      setGraphNodes([]);
      setGraphEdges([]);
    } finally {
      setGraphLoading(false);
    }
  }, []);

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
      addToast('warning', '无法加载文件树');
    }
  }, []);

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
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      addToast('error', `页面加载失败: ${msg}`);
      setPage(null);
      setContent('');
      setMetadata({});
      setBody('');
    }
  }, []);

  const handleBodyChange = useCallback((newBody: string) => {
    setBody(newBody);
    setContent(buildFrontMatter(metadata, newBody));
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
      addToast('success', '页面已保存');
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      addToast('error', `保存失败: ${msg}`);
    } finally {
      setSaving(false);
    }
  }, [page, content, addToast]);

  const hasMetadata = Object.keys(metadata).length > 0;

  return (
    <div className="flex h-full">
      {/* File Tree Sidebar */}
      <div className={cn(
        'bg-sidebar border-r border-sidebar-border overflow-y-auto transition-all duration-200',
        sidebarCollapsed ? 'w-10' : 'w-44',
      )}>
        {!sidebarCollapsed && (
          <>
            <div className="px-3 py-2 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Pages</div>
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
        <div className="h-10 bg-background border-b border-border flex items-center px-3 gap-2 shrink-0">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="text-muted-foreground hover:text-foreground text-sm p-1 rounded hover:bg-muted transition-colors"
            title={sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'}
          >
            {sidebarCollapsed ? '▶' : '◀'}
          </button>
          {page && <span className="text-sm text-foreground font-medium truncate">{page.page_name}</span>}
          <div className="ml-auto flex gap-1">
            {(['edit', 'graph'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  'px-2.5 py-1 text-xs rounded-md transition-colors font-medium',
                  mode === m ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                {m === 'graph' ? 'Graph' : m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
            {mode === 'graph' && (
              <button
                onClick={() => setShowLabels(!showLabels)}
                className={cn(
                  'px-2.5 py-1 text-xs rounded-md transition-colors font-medium',
                  showLabels ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                Labels
              </button>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={savePage}
              disabled={saving || !page}
              className="ml-1"
            >
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </div>

        {/* Front Matter Panel */}
        {hasMetadata && <FrontMatterPanel metadata={metadata} />}

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {mode === 'edit' && (
            <div className="flex h-full">
              <textarea
                value={body}
                onChange={(e) => handleBodyChange(e.target.value)}
                className="w-1/2 h-full bg-background text-foreground p-4 font-mono text-sm resize-none focus:outline-none border-r border-border"
                placeholder="Select a page or start writing..."
              />
              <div className="w-1/2 h-full overflow-y-auto p-4 markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {body || '*No content*'}
                </ReactMarkdown>
              </div>
            </div>
          )}
          {mode === 'graph' && (
            <div className="flex h-full">
              {/* Graph area */}
              <div className="w-1/2 h-full relative border-r border-border">
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
              {/* Preview area */}
              <div className="w-1/2 h-full overflow-y-auto p-4 markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {body || '*No content*'}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
