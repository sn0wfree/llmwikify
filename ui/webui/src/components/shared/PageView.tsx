/**
 * PageView — render wiki page content by page name.
 *
 * Fetches wiki page via api.wiki.readPage() and renders with react-markdown.
 * Non-modal (unlike WikiViewer), suitable for embedding in panels.
 *
 * Usage:
 *   <PageView pageName="factor/my-factor" />
 */

import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────

interface PageViewProps {
  pageName: string;
  wikiId?: string;
  className?: string;
}

interface WikiPage {
  page_name: string;
  content: string;
}

// ─── Component ──────────────────────────────────────────────

export function PageView({ pageName, wikiId, className }: PageViewProps) {
  const [page, setPage] = useState<WikiPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const fetchPage = async () => {
      try {
        // Dynamic import to avoid circular deps
        const { api } = await import('../../api');
        const result = wikiId
          ? await api.wiki.scoped.readPage(wikiId, pageName)
          : await api.wiki.readPage(pageName);
        if (!cancelled) {
          setPage(result);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchPage();
    return () => { cancelled = true; };
  }, [pageName, wikiId]);

  if (loading) {
    return (
      <div className={cn('p-4 text-sm text-muted-foreground', className)}>
        Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn('p-4 text-sm text-destructive', className)}>
        Failed to load page: {error}
      </div>
    );
  }

  if (!page) {
    return (
      <div className={cn('p-4 text-sm text-muted-foreground', className)}>
        Page not found
      </div>
    );
  }

  return (
    <div className={cn('prose prose-sm max-w-none dark:prose-invert', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {page.content}
      </ReactMarkdown>
    </div>
  );
}