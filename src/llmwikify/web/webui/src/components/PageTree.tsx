import { useState, useMemo } from 'react';
import { SearchResult } from '../api';

interface PageTreeProps {
  pages: SearchResult[];
  allTypes: string[];
  selectedPage: string | null;
  onSelect: (page: string) => void;
}

interface PageGroup {
  pageType: string;
  pages: Array<{ path: string; displayName: string }>;
}

const TYPE_ICONS: Record<string, string> = {
  sources: '📚',
  entities: '🏷️',
  concepts: '💡',
  papers: '📄',
  claims: '🎯',
  topics: '🏷️',
  root: '📝',
  overview: '📖',
  comparisons: '⚖️',
  synthesis: '🔬',
  other: '📄',
};

function getTypeColor(pageType: string, allTypes: string[]): string {
  if (!allTypes || allTypes.length === 0) return '#94a3b8';
  const idx = allTypes.indexOf(pageType);
  if (idx === -1) return '#94a3b8';
  const hue = (idx / allTypes.length) * 360;
  const sat = 60 + (idx % 3) * 8;
  const light = 45 + (idx % 2) * 10;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

export function PageTree({ pages, allTypes, selectedPage, onSelect }: PageTreeProps) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const filteredPages = useMemo(() => {
    if (!search) return pages;
    const q = search.toLowerCase();
    return pages.filter(
      (p) => p.page_name.toLowerCase().includes(q) ||
             p.page_type?.toLowerCase().includes(q)
    );
  }, [pages, search]);

  const groups = useMemo(() => {
    const groupMap = new Map<string, PageGroup>();

    filteredPages.forEach((p) => {
      const pageType = p.page_type || 'other';
      if (!groupMap.has(pageType)) {
        groupMap.set(pageType, { pageType, pages: [] });
      }
      groupMap.get(pageType)!.pages.push({
        path: p.page_name,
        displayName: p.page_name.split('/').pop()?.replace(/\.md$/, '') || p.page_name,
      });
    });

    const sorted = Array.from(groupMap.values()).sort((a, b) => {
      const aIdx = allTypes.indexOf(a.pageType);
      const bIdx = allTypes.indexOf(b.pageType);
      if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
      if (aIdx !== -1) return -1;
      if (bIdx !== -1) return 1;
      return a.pageType.localeCompare(b.pageType);
    });

    return sorted;
  }, [filteredPages, allTypes]);

  const toggleGroup = (pt: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(pt)) next.delete(pt);
      else next.add(pt);
      return next;
    });
  };

  return (
    <div className="text-sm">
      <div className="px-2 py-2">
        <input
          type="text"
          placeholder="Filter pages..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      {groups.map((group) => {
        const isExpanded = expanded.has(group.pageType);
        const isSelectedInGroup = group.pages.some((p) => p.path === selectedPage);
        const color = getTypeColor(group.pageType, allTypes);
        const icon = TYPE_ICONS[group.pageType] || TYPE_ICONS.other;

        return (
          <div key={group.pageType}>
            <button
              onClick={() => toggleGroup(group.pageType)}
              className={`w-full text-left px-2 py-1.5 flex items-center gap-1.5 transition-colors ${
                isSelectedInGroup
                  ? 'bg-blue-600/20'
                  : 'hover:bg-slate-700'
              }`}
            >
              <span className="text-xs w-3">{isExpanded ? '▼' : '▶'}</span>
              <span className="text-xs">{icon}</span>
              <span
                className="text-xs font-semibold flex-1 truncate"
                style={{ color }}
              >
                {group.pageType}
              </span>
              <span className="text-xs text-slate-500">{group.pages.length}</span>
            </button>

            {isExpanded && (
              <div>
                {group.pages.map((p) => (
                  <button
                    key={p.path}
                    onClick={() => onSelect(p.path)}
                    className={`w-full text-left px-3 py-1 pl-8 text-sm truncate transition-colors ${
                      selectedPage === p.path
                        ? 'bg-blue-600/30 text-blue-300'
                        : 'text-slate-300 hover:bg-slate-700'
                    }`}
                    title={p.path}
                  >
                    {p.displayName}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {groups.length === 0 && (
        <div className="px-3 py-4 text-center text-xs text-slate-500">
          {search ? 'No matching pages' : 'No pages found'}
        </div>
      )}
    </div>
  );
}