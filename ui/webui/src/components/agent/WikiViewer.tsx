import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, type WikiPage } from '../../api';
import { Dialog, DialogContent, DialogTitle } from '../ui/dialog';
import { X } from 'lucide-react';

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
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="max-w-3xl sm:max-w-3xl max-h-[85vh] flex flex-col"
        showCloseButton={false}
      >
        {/* Header */}
        <div className="flex items-center gap-3 shrink-0 -mt-4 -mx-4 px-4 py-3 border-b border-border">
          <div className="flex-1 min-w-0">
            <DialogTitle className="text-sm font-medium text-foreground truncate">
              {pageName}
            </DialogTitle>
            {page?.file && (
              <div className="text-[10px] text-muted-foreground mt-0.5 opacity-60 truncate">
                {page.file}
              </div>
            )}
          </div>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 shrink-0">
            Wiki
          </span>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground shrink-0 ml-1"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
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
      </DialogContent>
    </Dialog>
  );
}
