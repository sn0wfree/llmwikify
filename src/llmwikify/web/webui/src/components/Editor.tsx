import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, WikiPage } from '../api';
import { useToast } from './Toast';
import { FrontMatterPanel, FrontMatterData } from './FrontMatterPanel';

interface EditorProps {
  selectedPage: string | null;
  onPageSelect: (page: string) => void;
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

export function Editor({ selectedPage, onPageSelect }: EditorProps) {
  const { addToast } = useToast();
  const [page, setPage] = useState<WikiPage | null>(null);
  const [content, setContent] = useState('');
  const [metadata, setMetadata] = useState<FrontMatterData>({});
  const [body, setBody] = useState('');
  const [mode, setMode] = useState<'edit' | 'preview' | 'split'>('split');
  const [saving, setSaving] = useState(false);
  const [fileTree, setFileTree] = useState<Array<{ name: string; path: string }>>([]);

  useEffect(() => {
    loadTree();
  }, []);

  useEffect(() => {
    if (selectedPage) {
      loadPage(selectedPage);
    }
  }, [selectedPage]);

  const loadTree = useCallback(async () => {
    try {
      const results = await api.wiki.search('', 100);
      const tree = results.map((r) => ({
        name: r.page_name.split('/').pop() || r.page_name,
        path: r.page_name,
      }));
      setFileTree(tree);
    } catch {
      addToast('warning', '无法加载文件树');
    }
  }, []);

  const loadPage = useCallback(async (name: string) => {
    try {
      const data = await api.wiki.readPage(name);
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
      await api.wiki.writePage(page.page_name, content);
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
      {/* File Tree */}
      <div className="w-48 bg-slate-800/50 border-r border-slate-700 overflow-y-auto">
        <div className="p-2 text-xs font-semibold text-slate-400 uppercase">Pages</div>
        {fileTree.map((f) => (
          <button
            key={f.path}
            onClick={() => onPageSelect(f.path)}
            className={`w-full text-left px-3 py-1.5 text-sm truncate transition-colors ${
              page?.page_name === f.path
                ? 'bg-blue-600/20 text-blue-400'
                : 'text-slate-300 hover:bg-slate-700'
            }`}
          >
            {f.name.replace('.md', '')}
          </button>
        ))}
      </div>

      {/* Editor Area */}
      <div className="flex-1 flex flex-col">
        {/* Toolbar */}
        <div className="h-10 bg-slate-800 border-b border-slate-700 flex items-center px-4 gap-2">
          {page && <span className="text-sm text-slate-300">{page.page_name}</span>}
          <div className="ml-auto flex gap-1">
            {(['edit', 'split', 'preview'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2 py-1 text-xs rounded ${
                  mode === m ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-700'
                }`}
              >
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
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
            <textarea
              value={body}
              onChange={(e) => handleBodyChange(e.target.value)}
              className="w-full h-full bg-slate-900 text-slate-100 p-4 font-mono text-sm resize-none focus:outline-none"
              placeholder="Select a page or start writing..."
            />
          )}
          {mode === 'preview' && (
            <div className="w-full h-full overflow-y-auto p-4 markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content || '*No content*'}
              </ReactMarkdown>
            </div>
          )}
          {mode === 'split' && (
            <div className="flex h-full">
              <textarea
                value={body}
                onChange={(e) => handleBodyChange(e.target.value)}
                className="w-1/2 h-full bg-slate-900 text-slate-100 p-4 font-mono text-sm resize-none focus:outline-none border-r border-slate-700"
              />
              <div className="w-1/2 h-full overflow-y-auto p-4 markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {content || '*No content*'}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
