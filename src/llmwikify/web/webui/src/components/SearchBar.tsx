import { useState, useRef, useCallback, useEffect } from 'react';
import { api, SearchResult } from '../api';

interface SearchBarProps {
  onResult?: (page: string) => void;
}

export function SearchBar({ onResult }: SearchBarProps) {
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
      const r = await api.wiki.search(q, 10);
      setResults(r);
      setShowDropdown(r.length > 0);
    } catch {
      setResults([]);
      setShowDropdown(false);
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

  const handleSelect = (pageName: string) => {
    setQuery('');
    setResults([]);
    setShowDropdown(false);
    onResult?.(pageName);
  };

  // Close dropdown when clicking outside
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
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={handleChange}
            onFocus={() => results.length > 0 && setShowDropdown(true)}
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

      {/* Dropdown results */}
      {showDropdown && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded shadow-xl z-50 max-h-80 overflow-y-auto">
          {results.map((r, i) => (
            <div
              key={i}
              onClick={() => handleSelect(r.page_name)}
              className="p-3 border-b border-slate-700 last:border-b-0 hover:bg-slate-700 cursor-pointer transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-blue-400">{r.page_name}</span>
                <span className="text-xs text-slate-500">score: {r.score?.toFixed(2)}</span>
              </div>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                {r.snippet || r.content?.substring(0, 150) || ''}
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

      {/* No results */}
      {showDropdown && results.length === 0 && query && !loading && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded shadow-xl z-50 p-4 text-center text-slate-500 text-sm">
          No results found
        </div>
      )}
    </div>
  );
}
