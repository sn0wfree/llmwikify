import { useState, useMemo, useEffect } from 'react';
import { SearchResult } from '../api';

interface PageTreeProps {
  pages: SearchResult[];
  allTypes: string[];
  selectedPage: string | null;
  onSelect: (page: string) => void;
}

interface PageGroup {
  pageType: string;
  tree: TreeNode[];
  flatCount: number;
}

interface TreeNode {
  name: string;
  path: string;
  type: 'directory' | 'file';
  children: TreeNode[];
  fullPath?: string;
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
  research: '🔬',
  factors: '📊',
  company: '🏢',
  industry: '🏭',
  daily: '📅',
  weekly: '📅',
  monthly: '📅',
  quarterly: '📅',
  yearly: '📅',
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

function countNodes(node: TreeNode): number {
  if (node.type === 'file') return 1;
  return node.children.reduce((sum, child) => sum + countNodes(child), 0);
}

function buildTree(pages: Array<{ path: string; fullPath: string }>): TreeNode[] {
  const root: TreeNode[] = [];

  for (const page of pages) {
    const parts = page.path.split('/');
    let current = root;

    for (let i = 0; i < parts.length - 1; i++) {
      const dirName = parts[i];
      let dir = current.find((n) => n.name === dirName && n.type === 'directory');
      if (!dir) {
        dir = {
          name: dirName,
          path: parts.slice(0, i + 1).join('/'),
          type: 'directory',
          children: [],
        };
        current.push(dir);
      }
      current = dir.children;
    }

    const fileName = parts[parts.length - 1].replace(/\.md$/, '');
    current.push({
      name: fileName,
      path: page.path,
      type: 'file',
      children: [],
      fullPath: page.fullPath,
    });
  }

  return root;
}

function TreeNodeComponent({
  node,
  depth,
  expanded,
  onToggle,
  onSelect,
  selectedPage,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  selectedPage: string | null;
}) {
  const isExpanded = expanded.has(node.path);
  const isSelected = node.type === 'file' && node.fullPath === selectedPage;

  if (node.type === 'directory') {
    const childCount = countNodes(node);
    return (
      <div>
        <button
          onClick={() => onToggle(node.path)}
          className={`w-full text-left px-2 py-1 flex items-center gap-1.5 transition-colors hover:bg-slate-700`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <span className="text-xs w-3 text-slate-500">{isExpanded ? '▼' : '▶'}</span>
          <span className="text-xs">{isExpanded ? '📂' : '📁'}</span>
          <span className="text-xs text-slate-300 flex-1 truncate">{node.name}</span>
          <span className="text-xs text-slate-500">{childCount}</span>
        </button>
        {isExpanded &&
          node.children.map((child) => (
            <TreeNodeComponent
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
              selectedPage={selectedPage}
            />
          ))}
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelect(node.fullPath || node.path)}
      className={`w-full text-left px-2 py-1 text-sm truncate transition-colors ${
        isSelected ? 'bg-blue-600/30 text-blue-300' : 'text-slate-300 hover:bg-slate-700'
      }`}
      style={{ paddingLeft: `${depth * 16 + 24}px` }}
      title={node.fullPath || node.path}
    >
      {node.name}
    </button>
  );
}

export function PageTree({ pages, allTypes, selectedPage, onSelect }: PageTreeProps) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selectedPage) return;
    const pageType = pages.find((p) => p.page_name === selectedPage)?.page_type || 'other';
    setExpanded((prev) => {
      if (prev.has(pageType)) return prev;
      const next = new Set(prev);
      next.add(pageType);
      return next;
    });
  }, [selectedPage, pages]);

  const filteredPages = useMemo(() => {
    const base = pages.filter((p) => p.page_name !== 'log');
    if (!search) return base;
    const q = search.toLowerCase();
    return base.filter(
      (p) =>
        p.page_name.toLowerCase().includes(q) || p.page_type?.toLowerCase().includes(q)
    );
  }, [pages, search]);

  const groups = useMemo(() => {
    const groupMap = new Map<string, Array<{ path: string; fullPath: string }>>();
    const pinnedPages: Array<{ path: string; fullPath: string }> = [];

    filteredPages.forEach((p) => {
      if (p.page_name === 'index' || p.page_name === 'overview') {
        pinnedPages.push({ path: p.page_name, fullPath: p.page_name });
        return;
      }
      const pageType = p.page_type || 'other';
      if (!groupMap.has(pageType)) {
        groupMap.set(pageType, []);
      }
      groupMap.get(pageType)!.push({ path: p.page_name, fullPath: p.page_name });
    });

    const sorted: PageGroup[] = Array.from(groupMap.entries())
      .map(([pageType, pages]) => ({
        pageType,
        tree: buildTree(pages),
        flatCount: pages.length,
      }))
      .sort((a, b) => {
        const aIdx = allTypes.indexOf(a.pageType);
        const bIdx = allTypes.indexOf(b.pageType);
        if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
        if (aIdx !== -1) return -1;
        if (bIdx !== -1) return 1;
        return a.pageType.localeCompare(b.pageType);
      });

    if (pinnedPages.length > 0) {
      return [{ pageType: 'pinned', tree: buildTree(pinnedPages), flatCount: pinnedPages.length }, ...sorted];
    }
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

  const toggleDir = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
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
        const isPinned = group.pageType === 'pinned';
        const isExpanded = expanded.has(group.pageType);
        const color = getTypeColor(group.pageType, allTypes);
        const icon = isPinned ? '⭐' : TYPE_ICONS[group.pageType] || '📁';

        if (isPinned) {
          return (
            <div key="pinned" className="mb-1">
              <div className="px-2 py-1 text-xs text-slate-400 uppercase font-semibold">Pinned</div>
              {group.tree.map((node) => (
                <TreeNodeComponent
                  key={node.path}
                  node={node}
                  depth={0}
                  expanded={expanded}
                  onToggle={toggleDir}
                  onSelect={onSelect}
                  selectedPage={selectedPage}
                />
              ))}
            </div>
          );
        }

        return (
          <div key={group.pageType}>
            <button
              onClick={() => toggleGroup(group.pageType)}
              className="w-full text-left px-2 py-1.5 flex items-center gap-1.5 transition-colors hover:bg-slate-700"
            >
              <span className="text-xs w-3 text-slate-500">{isExpanded ? '▼' : '▶'}</span>
              <span className="text-xs">{icon}</span>
              <span className="text-xs font-semibold flex-1 truncate" style={{ color }}>
                {group.pageType}
              </span>
              <span className="text-xs text-slate-500">{group.flatCount}</span>
            </button>

            {isExpanded && (
              <div>
                {group.tree.map((node) => (
                  <TreeNodeComponent
                    key={node.path}
                    node={node}
                    depth={1}
                    expanded={expanded}
                    onToggle={toggleDir}
                    onSelect={onSelect}
                    selectedPage={selectedPage}
                  />
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
