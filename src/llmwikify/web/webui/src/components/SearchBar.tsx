import { useState, useRef, useCallback } from 'react';
import { api, SearchResult } from '../api';

interface SearchBarProps {
  standalone?: boolean;
  onResult?: (page: string) => void;
}

export function SearchBar({ standalone, onResult }: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const r = await api.wiki.search(q);
      setResults(r);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

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

  const containerClass = standalone
    ? 'flex-1 overflow-y-auto p-4'
    : 'flex-1';

  return (
    <div className={containerClass}>
      <form onSubmit={handleSearch} className={`${standalone ? 'max-w-2xl mx-auto mb-4' : ''}`}>
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={handleChange}
            placeholder="Search wiki..."
            className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm text-white"
          >
            {loading ? '...' : 'Search'}
          </button>
        </div>
      </form>

      {results.length > 0 && (
        <div className="space-y-2">
          {results.map((r, i) => (
            <div
              key={i}
              onClick={() => onResult?.(r.page_name)}
              className="p-3 bg-slate-800 rounded border border-slate-700 hover:border-blue-500 cursor-pointer transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-blue-400">{r.page_name}</span>
                <span className="text-xs text-slate-500">score: {r.score?.toFixed(2)}</span>
              </div>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                {r.content?.substring(0, 150)}...
              </p>
              {r.has_sink && (
                <span className="inline-block mt-1 px-1.5 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded">
                  {r.sink_entries} pending
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {results.length === 0 && query && !loading && (
        <p className="text-center text-slate-500 text-sm mt-8">No results found</p>
      )}
    </div>
  );
}
