import { useState, useMemo } from 'react';
import { SearchResult } from '../api';

interface PageTreeProps {
  pages: SearchResult[];
  selectedPage: string | null;
  onSelect: (page: string) => void;
}

interface PageGroup {
  name: string;
  displayName: string;
  pages: Array<{ path: string; displayName: string }>;
}

function getGroupFromPath(pageName: string): string {
  const parts = pageName.split('/');
  return parts.length > 1 ? parts[0] : 'other';
}

function getDisplayNameFromPath(pageName: string): string {
  const parts = pageName.split('/');
  const name = parts[parts.length - 1];
  return name.replace(/\.md$/, '');
}

const GROUP_DISPLAY_NAMES: Record<string, string> = {
  sources: 'Sources',
  entities: 'Entities',
  concepts: 'Concepts',
  papers: 'Papers',
  claims: 'Claims',
  topics: 'Topics',
  other: 'Other',
};

export function PageTree({ pages, selectedPage, onSelect }: PageTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const groups = useMemo(() => {
    const groupMap = new Map<string, PageGroup>();

    pages.forEach((p) => {
      const groupKey = getGroupFromPath(p.page_name);
      if (!groupMap.has(groupKey)) {
        groupMap.set(groupKey, {
          name: groupKey,
          displayName: GROUP_DISPLAY_NAMES[groupKey] || groupKey.charAt(0).toUpperCase() + groupKey.slice(1),
          pages: [],
        });
      }
      groupMap.get(groupKey)!.pages.push({
        path: p.page_name,
        displayName: getDisplayNameFromPath(p.page_name),
      });
    });

    // Sort: known groups first (alphabetical), then 'other', then unknown groups
    const knownOrder = ['sources', 'entities', 'concepts', 'papers', 'claims', 'topics'];
    const sorted = Array.from(groupMap.values()).sort((a, b) => {
      const aIdx = knownOrder.indexOf(a.name);
      const bIdx = knownOrder.indexOf(b.name);
      if (a.name === 'other') return 1;
      if (b.name === 'other') return -1;
      if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
      if (aIdx !== -1) return -1;
      if (bIdx !== -1) return 1;
      return a.displayName.localeCompare(b.displayName);
    });

    return sorted;
  }, [pages]);

  // Auto-expand all groups on first load
  const allGroupNames = useMemo(() => groups.map((g) => g.name), [groups]);

  const toggleGroup = (groupName: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) next.delete(groupName);
      else next.add(groupName);
      return next;
    });
  };

  return (
    <div className="text-sm">
      {groups.map((group) => {
        const isExpanded = expanded.has(group.name);
        const isSelectedInGroup = group.pages.some((p) => p.path === selectedPage);

        return (
          <div key={group.name}>
            <button
              onClick={() => toggleGroup(group.name)}
              className={`w-full text-left px-2 py-1.5 flex items-center gap-1 transition-colors ${
                isSelectedInGroup
                  ? 'bg-blue-600/10 text-blue-400'
                  : 'hover:bg-slate-700 text-slate-400'
              }`}
            >
              <span className="text-xs w-3">{isExpanded ? '▼' : '▶'}</span>
              <span className="text-xs font-semibold flex-1">{group.displayName}</span>
              <span className="text-xs text-slate-500">{group.pages.length}</span>
            </button>

            {isExpanded && (
              <div>
                {group.pages.map((p) => (
                  <button
                    key={p.path}
                    onClick={() => onSelect(p.path)}
                    className={`w-full text-left px-3 py-1.5 pl-7 text-sm truncate transition-colors ${
                      selectedPage === p.path
                        ? 'bg-blue-600/20 text-blue-400'
                        : 'text-slate-300 hover:bg-slate-700'
                    }`}
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
          No pages found
        </div>
      )}
    </div>
  );
}
