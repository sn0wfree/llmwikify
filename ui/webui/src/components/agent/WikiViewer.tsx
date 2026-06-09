import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, type WikiPage } from '../../api';

interface Props {
  pageName: string;
  wikiId?: string;
  onClose: () => void;
}

export function WikiViewer({ pageName, wikiId, onClose }: Props) {
  const [page, setPage] = useState<WikiPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = wikiId
          ? await api.wiki.scoped.readPage(wikiId, pageName)
          : await api.wiki.readPage(pageName);
        if (!cancelled) setPage(data);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [pageName, wikiId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-3xl max-h-[85vh] mx-4 bg-[var(--bg-secondary)] rounded-lg shadow-xl border border-[var(--border)] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-[var(--border)] flex items-center gap-3 shrink-0">
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-medium text-[var(--text-primary)] truncate">
              {pageName}
            </h3>
            {page?.file && (
              <div className="text-[10px] text-[var(--text-secondary)] mt-0.5 opacity-60 truncate">
                {page.file}
              </div>
            )}
          </div>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 shrink-0">
            Wiki
          </span>
          <button
            onClick={onClose}
            className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] shrink-0 ml-1"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex items-center justify-center py-12 text-sm text-[var(--text-secondary)]">
              Loading wiki page...
            </div>
          )}
          {error && (
            <div className="flex items-center justify-center py-12 text-sm text-red-400">
              {error}
            </div>
          )}
          {page && (
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {page.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
