import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Loader2, FileText, Sparkles, X } from 'lucide-react';
import { api, SearchResult } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { Dialog, DialogContent } from '../ui/dialog';
import { cn } from '@/lib/utils';

interface SinkEntry {
  page_name: string;
  entry_count: number;
  urgency: string;
}

export function UnifiedSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [sinks, setSinks] = useState<SinkEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { currentWikiId, isMultiWikiMode } = useWikiStore();

  const fetchSinks = useCallback(async () => {
    try {
      const data = isMultiWikiMode && currentWikiId
        ? await api.wiki.scoped.sinkStatus(currentWikiId)
        : await api.wiki.sinkStatus();
      setSinks(data.sinks || []);
    } catch {
      setSinks([]);
    }
  }, [currentWikiId, isMultiWikiMode]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      fetchSinks();
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, fetchSinks]);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); return; }
    setLoading(true);
    try {
      let r: SearchResult[];
      if (isMultiWikiMode && currentWikiId) {
        r = await api.wiki.scoped.search(currentWikiId, q, 8);
      } else {
        r = await api.wiki.search(q, 8);
      }
      setResults(r || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [currentWikiId, isMultiWikiMode]);

  const handleChange = (val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 250);
  };

  const matchingSinks = query.trim()
    ? sinks.filter((s) => s.page_name.toLowerCase().includes(query.toLowerCase()))
    : [];

  const handleSelect = (page: string) => {
    setQuery('');
    setResults([]);
    onClose();
    navigate(`/edit?page=${encodeURIComponent(page)}`);
  };

  const hasResults = results.length > 0 || matchingSinks.length > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className="!top-[15vh] !-translate-y-0 left-1/2 -translate-x-1/2 max-w-xl sm:max-w-xl glass-strong border border-border/60 shadow-elevated overflow-hidden p-0 animate-slide-up gap-0"
        showCloseButton={false}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40">
          <Search className="w-4 h-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            placeholder="Search pages, sinks…"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 text-muted-foreground animate-spin shrink-0" />
          ) : query ? (
            <button onClick={() => { setQuery(''); setResults([]); }} className="text-muted-foreground hover:text-foreground">
              <X className="w-3.5 h-3.5" />
            </button>
          ) : (
            <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-muted-foreground">ESC</kbd>
          )}
        </div>

        {query && !hasResults && !loading && (
          <div className="p-8 text-center text-sm text-muted-foreground">
            No results for "{query}"
          </div>
        )}

        {hasResults && (
          <div className="max-h-[60vh] overflow-y-auto">
            {results.length > 0 && (
              <>
                <div className="px-4 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.08em] bg-white/[0.02]">
                  Pages
                </div>
                {results.map((r, i) => (
                  <button
                    key={`page-${i}`}
                    onClick={() => handleSelect(r.page_name)}
                    className="w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-white/[0.04] transition-colors border-b border-border/20 last:border-b-0"
                  >
                    <FileText className="w-3.5 h-3.5 text-primary shrink-0" />
                    <span className="text-sm text-foreground flex-1 truncate">{r.page_name}</span>
                    {r.snippet && <span className="text-xs text-muted-foreground truncate max-w-[200px]">{r.snippet}</span>}
                    {r.has_sink && (
                      <span className="shrink-0 px-1 py-0.5 text-[10px] font-medium bg-warning/15 text-warning rounded">
                        {r.sink_entries} pending
                      </span>
                    )}
                  </button>
                ))}
              </>
            )}

            {matchingSinks.length > 0 && (
              <>
                <div className="px-4 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.08em] bg-white/[0.02]">
                  Sinks
                </div>
                {matchingSinks.map((s) => (
                  <div
                    key={`sink-${s.page_name}`}
                    className="px-4 py-2.5 flex items-center gap-3 hover:bg-white/[0.04] transition-colors cursor-pointer"
                    onClick={() => handleSelect(s.page_name)}
                  >
                    <Sparkles className="w-3.5 h-3.5 text-warning shrink-0" />
                    <span className="text-sm text-foreground flex-1 truncate">{s.page_name}</span>
                    <span className="text-xs text-muted-foreground">{s.entry_count} entries</span>
                    <span className={cn(
                      'px-1 py-0.5 text-[10px] font-medium rounded',
                      s.urgency === 'ok' ? 'text-success bg-success/15' :
                      s.urgency === 'attention' ? 'text-warning bg-warning/15' :
                      s.urgency === 'aging' ? 'text-orange-400 bg-orange-500/15' :
                      'text-destructive bg-destructive/15',
                    )}>
                      {s.urgency}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {!query && (
          <div className="p-8 text-center text-sm text-muted-foreground">
            Type to search pages and sinks
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
