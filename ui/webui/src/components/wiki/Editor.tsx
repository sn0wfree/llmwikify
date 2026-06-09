import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, WikiPage, GraphNode, GraphEdge } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { useToast } from './Toast';
import { FrontMatterPanel, FrontMatterData } from './FrontMatterPanel';
import { GraphView } from './GraphView';
import { PageTree } from './PageTree';

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

  useEffect(() => {
    loadTree();
  }, []);

  useEffect(() => {
    if (selectedPage) {
      loadPage(selectedPage, currentWikiId || undefined);
      loadGraphData(selectedPage, currentWikiId || undefined);
    }
  }, [selectedPage, currentWikiId]);

  useEffect(() => {
    if (currentWikiId) {
      loadTree(currentWikiId);
    }
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
      {/* Page Tree */}
      <div className={`${sidebarCollapsed ? 'w-10' : 'w-40'} bg-slate-800/50 border-r border-slate-700 overflow-y-auto transition-all duration-200`}>
        {!sidebarCollapsed && (
          <>
            <div className="p-2 text-xs font-semibold text-slate-400 uppercase">Pages</div>
            <PageTree
              pagesByType={pagesByType}
              selectedPage={page?.page_name || null}
              onSelect={handlePageSelect}
            />
          </>
        )}
      </div>

      {/* Editor Area */}
      <div className="flex-1 flex flex-col">
        {/* Toolbar */}
        <div className="h-10 bg-slate-800 border-b border-slate-700 flex items-center px-4 gap-2">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="text-slate-400 hover:text-slate-200 text-sm"
            title={sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'}
          >
            {sidebarCollapsed ? '▶' : '◀'}
          </button>
          {page && <span className="text-sm text-slate-300">{page.page_name}</span>}
          <div className="ml-auto flex gap-1">
            {(['edit', 'graph'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2 py-1 text-xs rounded ${
                  mode === m ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-700'
                }`}
              >
                {m === 'graph' ? 'Graph' : m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
            {mode === 'graph' && (
              <button
                onClick={() => setShowLabels(!showLabels)}
                className={`px-2 py-1 text-xs rounded ${showLabels ? 'bg-slate-600 text-white' : 'text-slate-400 hover:bg-slate-700'}`}
              >
                Labels
              </button>
            )}
            <button
              onClick={savePage}
              disabled={saving || !page}
              className="ml-2 px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-white"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
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
                className="w-1/2 h-full bg-slate-900 text-slate-100 p-4 font-mono text-sm resize-none focus:outline-none border-r border-slate-700"
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
              <div className="w-1/2 h-full relative border-r border-slate-700">
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
