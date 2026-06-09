/**
 * CrossWikiSearch - Enhanced search bar for cross-wiki search.
 * Glass morphism + segmented control mode toggle.
 */

import { useState, useEffect, useRef } from 'react';
import { Search, Loader2, FileText, BookOpen, X } from 'lucide-react';
import { api, SearchResult } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

interface CrossWikiSearchProps {
  onResult?: (pageName: string, wikiId: string) => void;
}

interface CrossWikiResult extends SearchResult {
  wiki_id: string;
  wiki_name: string;
}

export function CrossWikiSearch({ onResult }: CrossWikiSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CrossWikiResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [searchMode, setSearchMode] = useState<'current' | 'all'>('current');
  const { currentWikiId, wikis, isMultiWikiMode } = useWikiStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  // ⌘K / Ctrl+K to focus
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
      if (e.key === 'Escape') {
        setIsOpen(false);
        inputRef.current?.blur();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSearch = async (searchQuery: string) => {
    if (searchQuery.length < 2) {
      setResults([]);
      setIsOpen(false);
      return;
    }
    setIsSearching(true);
    try {
      let searchResults: CrossWikiResult[];

      if (searchMode === 'all' && isMultiWikiMode) {
        const response = await api.search.cross(searchQuery, 15);
        searchResults = response.results.map((r) => ({
          page_name: r.page_name as string,
          content: r.content as string || '',
          snippet: r.snippet as string,
          score: r.score as number || 0,
          wiki_id: r.wiki_id as string,
          wiki_name: r.wiki_name as string,
        }));
      } else {
        if (isMultiWikiMode && currentWikiId) {
          const wikiResults = await api.wiki.scoped.search(currentWikiId, searchQuery, 15);
          const wiki = wikis.find((w) => w.wiki_id === currentWikiId);
          searchResults = wikiResults.map((r) => ({
            ...r,
            wiki_id: currentWikiId,
            wiki_name: wiki?.name || currentWikiId,
          }));
        } else {
          const wikiResults = await api.wiki.search(searchQuery, 15);
          const wiki = wikis.find((w) => w.is_default);
          const wikiId = wiki?.wiki_id || 'default';
          searchResults = wikiResults.map((r) => ({
            ...r,
            wiki_id: wikiId,
            wiki_name: wiki?.name || wikiId,
          }));
        }
      }
      setResults(searchResults);
      setIsOpen(searchResults.length > 0);
    } catch (err) {
      console.error('Search failed:', err);
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  const handleInputChange = (value: string) => {
    setQuery(value);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => handleSearch(value), 300);
  };

  const handleResultClick = (result: CrossWikiResult) => {
    setIsOpen(false);
    setQuery('');
    onResult?.(result.page_name, result.wiki_id);
  };

  return (
    <div ref={wrapperRef} className="relative flex-1 max-w-2xl">
      {/* Input row */}
      <div className="relative glow-border rounded-lg">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => query.length >= 2 && results.length > 0 && setIsOpen(true)}
          placeholder={`Search ${searchMode === 'all' ? 'all wikis' : 'this wiki'}…`}
          className={cn(
            'w-full pl-9 pr-20 py-2 text-sm rounded-lg',
            'bg-white/[0.04] border border-border/50',
            'text-foreground placeholder:text-muted-foreground',
            'focus:outline-none focus:bg-white/[0.06]',
            'transition-colors',
          )}
        />
        {isSearching ? (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <Loader2 className="w-3.5 h-3.5 text-muted-foreground animate-spin" />
          </div>
        ) : query ? (
          <button
            onClick={() => { setQuery(''); setResults([]); setIsOpen(false); }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Clear"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        ) : (
          <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-muted-foreground pointer-events-none">
            ⌘K
          </kbd>
        )}
      </div>

      {/* Mode toggle (multi-wiki only) */}
      {isMultiWikiMode && (
        <div className="flex items-center gap-1 mt-1.5">
          <div className="inline-flex p-0.5 rounded-md bg-white/[0.04] border border-border/40">
            <button
              onClick={() => setSearchMode('current')}
              className={cn(
                'px-2 py-0.5 text-[10px] font-medium rounded transition-colors',
                searchMode === 'current'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              This Wiki
            </button>
            <button
              onClick={() => setSearchMode('all')}
              className={cn(
                'px-2 py-0.5 text-[10px] font-medium rounded transition-colors',
                searchMode === 'all'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              All Wikis
            </button>
          </div>
        </div>
      )}

      {/* Results dropdown */}
      {isOpen && results.length > 0 && (
        <div className="absolute left-0 right-0 mt-1.5 glass-strong rounded-lg shadow-elevated z-50 max-h-96 overflow-y-auto animate-slide-up">
          {results.map((result, index) => (
            <button
              key={`${result.wiki_id}-${result.page_name}-${index}`}
              onClick={() => handleResultClick(result)}
              className="w-full text-left p-3 border-b border-border/30 last:border-b-0 hover:bg-white/[0.04] transition-colors group"
            >
              <div className="flex items-start gap-2.5">
                <FileText className="w-3.5 h-3.5 text-primary mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground truncate flex-1">
                      {result.page_name}
                    </span>
                    {searchMode === 'all' && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-primary/15 text-primary shrink-0">
                        <BookOpen className="w-2.5 h-2.5" />
                        {result.wiki_name}
                      </span>
                    )}
                  </div>
                  {result.snippet && (
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                      {result.snippet}
                    </p>
                  )}
                </div>
                {result.score !== undefined && (
                  <span className="text-[10px] font-mono text-muted-foreground tabular-nums shrink-0">
                    {result.score.toFixed(2)}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* No results */}
      {isOpen && results.length === 0 && !isSearching && query.length >= 2 && (
        <div className="absolute left-0 right-0 mt-1.5 glass-strong rounded-lg shadow-elevated z-50 p-6 text-center text-xs text-muted-foreground animate-slide-up">
          No results found
        </div>
      )}
    </div>
  );
}
