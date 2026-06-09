import { useState, useRef, useCallback, useEffect } from 'react';
import { Search, Loader2, FileText, Sparkles } from 'lucide-react';
import { api, SearchResult } from '../../api';
import { cn } from '@/lib/utils';

interface SearchBarProps {
  onResult?: (page: string) => void;
  currentWikiId?: string | null;
  isMultiWikiMode?: boolean;
}

export function SearchBar({ onResult, currentWikiId, isMultiWikiMode }: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      setShowDropdown(false);
      return;
    }
    setLoading(true);
    try {
      let r: SearchResult[];
      if (isMultiWikiMode && currentWikiId) {
        r = await api.wiki.scoped.search(currentWikiId, q, 10);
      } else {
        r = await api.wiki.search(q, 10);
      }
      setResults(r);
      setShowDropdown(r.length > 0);
    } catch {
      setResults([]);
      setShowDropdown(false);
    } finally {
      setLoading(false);
    }
  }, [currentWikiId, isMultiWikiMode]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    doSearch(query);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 300);
  };

  const handleSelect = (pageName: string) => {
    setQuery('');
    setResults([]);
    setShowDropdown(false);
    onResult?.(pageName);
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={wrapperRef} className="relative flex-1">
      <form onSubmit={handleSearch}>
        <div className="relative glow-border rounded-lg">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={handleChange}
            onFocus={() => results.length > 0 && setShowDropdown(true)}
            placeholder="Search wiki…"
            className={cn(
              'w-full pl-9 pr-20 py-2 text-sm rounded-lg',
              'bg-white/[0.04] border border-border/50',
              'text-foreground placeholder:text-muted-foreground',
              'focus:outline-none focus:bg-white/[0.06]',
              'transition-colors',
            )}
          />
          {loading ? (
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <Loader2 className="w-3.5 h-3.5 text-muted-foreground animate-spin" />
            </div>
          ) : (
            <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-muted-foreground pointer-events-none">
              Enter
            </kbd>
          )}
        </div>
      </form>

      {/* Dropdown results */}
      {showDropdown && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1.5 glass-strong rounded-lg shadow-elevated z-50 max-h-80 overflow-y-auto animate-slide-up">
          {results.map((r, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleSelect(r.page_name)}
              className="w-full text-left p-3 border-b border-border/30 last:border-b-0 hover:bg-white/[0.04] transition-colors"
            >
              <div className="flex items-center gap-2">
                <FileText className="w-3.5 h-3.5 text-primary shrink-0" />
                <span className="text-sm font-medium text-foreground truncate flex-1">
                  {r.page_name}
                </span>
                {r.score !== undefined && (
                  <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
                    {r.score.toFixed(2)}
                  </span>
                )}
              </div>
              {r.snippet && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2 pl-5.5 ml-0.5">
                  {r.snippet}
                </p>
              )}
              {r.has_sink && (
                <span className="inline-flex items-center gap-1 mt-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-warning/15 text-warning rounded">
                  <Sparkles className="w-2.5 h-2.5" />
                  {r.sink_entries} pending
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* No results */}
      {showDropdown && results.length === 0 && query && !loading && (
        <div className="absolute top-full left-0 right-0 mt-1.5 glass-strong rounded-lg shadow-elevated z-50 p-6 text-center animate-slide-up">
          <div className="text-xs text-muted-foreground">No results for "{query}"</div>
        </div>
      )}
    </div>
  );
}
