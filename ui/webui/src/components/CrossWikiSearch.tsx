/**
 * CrossWikiSearch - Enhanced search bar for cross-wiki search.
 * Supports toggling between single wiki and cross-wiki search modes.
 */

import { useState, useEffect, useRef } from 'react';
import { api, SearchResult } from '../api';
import { useWikiStore } from '../stores/wikiStore';

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
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  // Keyboard shortcut: Ctrl+K or Cmd+K
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

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (!(e.target as Element).closest('.search-container')) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
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
        // Cross-wiki search
        const response = await api.search.cross(searchQuery, 15);
        searchResults = response.results.map(r => ({
          page_name: r.page_name as string,
          content: r.content as string || '',
          snippet: r.snippet as string,
          score: r.score as number || 0,
          wiki_id: r.wiki_id as string,
          wiki_name: r.wiki_name as string,
        }));
      } else {
        // Single wiki search
        if (isMultiWikiMode && currentWikiId) {
          const wikiResults = await api.wiki.scoped.search(currentWikiId, searchQuery, 15);
          const wiki = wikis.find(w => w.wiki_id === currentWikiId);
          searchResults = wikiResults.map(r => ({
            ...r,
            wiki_id: currentWikiId,
            wiki_name: wiki?.name || currentWikiId,
          }));
        } else {
          const wikiResults = await api.wiki.search(searchQuery, 15);
          const wiki = wikis.find(w => w.is_default);
          const wikiId = wiki?.wiki_id || 'default';
          searchResults = wikiResults.map(r => ({
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

    // Debounce search
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      handleSearch(value);
    }, 300);
  };

  const handleResultClick = (result: CrossWikiResult) => {
    setIsOpen(false);
    setQuery('');
    onResult?.(result.page_name, result.wiki_id);
  };

  const highlightMatch = (text: string, query: string) => {
    if (!query) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark class="bg-yellow-500/30 text-yellow-200 rounded px-0.5">$1</mark>');
  };

  return (
    <div className="relative search-container flex-1 max-w-xl">
      {/* Search input */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => query.length >= 2 && results.length > 0 && setIsOpen(true)}
          placeholder={`Search ${searchMode === 'all' ? 'all wikis' : 'this wiki'}... (Ctrl+K)`}
          className="w-full px-4 py-2 pl-10 bg-slate-700 border border-slate-600 rounded-lg text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        {isSearching && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Search mode toggle (only in multi-wiki mode) */}
      {isMultiWikiMode && (
        <div className="flex gap-1 mt-1">
          <button
            onClick={() => setSearchMode('current')}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              searchMode === 'current'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            This Wiki
          </button>
          <button
            onClick={() => setSearchMode('all')}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              searchMode === 'all'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            All Wikis
          </button>
        </div>
      )}

      {/* Search results dropdown */}
      {isOpen && results.length > 0 && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto">
            {results.map((result, index) => (
              <button
                key={`${result.wiki_id}-${result.page_name}-${index}`}
                onClick={() => handleResultClick(result)}
                className="w-full px-4 py-3 text-left hover:bg-slate-700 transition-colors border-b border-slate-700 last:border-b-0"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-200 truncate">
                      {result.page_name}
                    </div>
                    {result.snippet && (
                      <div
                        className="text-xs text-slate-400 mt-1 line-clamp-2"
                        dangerouslySetInnerHTML={{
                          __html: highlightMatch(result.snippet, query),
                        }}
                      />
                    )}
                  </div>
                  {searchMode === 'all' && (
                    <span className="text-xs bg-slate-600 text-slate-300 px-2 py-0.5 rounded whitespace-nowrap">
                      {result.wiki_name}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {/* No results */}
      {isOpen && results.length === 0 && !isSearching && query.length >= 2 && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg z-50 p-4 text-center text-slate-400 text-sm">
            No results found
          </div>
        </>
      )}
    </div>
  );
}
