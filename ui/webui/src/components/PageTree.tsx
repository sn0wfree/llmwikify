import { useState, useMemo, useEffect } from 'react';

interface PageTreeProps {
  pagesByType: Record<string, string[]>;
  selectedPage: string | null;
  onSelect: (page: string) => void;
}

interface TreeNode {
  name: string;
  path: string;
  type: 'directory' | 'file';
  children: TreeNode[];
  fullPath?: string;
}

const DIR_ICONS: Record<string, string> = {
  sources: '📚',
  entities: '🏷️',
  concepts: '💡',
  papers: '📄',
  claims: '🎯',
  root: '📝',
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
          className="w-full text-left px-2 py-1 flex items-center gap-1.5 transition-colors hover:bg-slate-700"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <span className="text-xs w-3 text-slate-500">{isExpanded ? '▼' : '▶'}</span>
          <span className="text-xs">{isExpanded ? '📂' : (DIR_ICONS[node.name] || '📁')}</span>
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

export function PageTree({ pagesByType, selectedPage, onSelect }: PageTreeProps) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selectedPage) return;
    const dir = selectedPage.split('/')[0];
    setExpanded((prev) => {
      if (prev.has(dir)) return prev;
      const next = new Set(prev);
      next.add(dir);
      return next;
    });
  }, [selectedPage]);

  const allPages = useMemo(() => {
    const pages: Array<{ path: string; fullPath: string }> = [];
    for (const [dir, files] of Object.entries(pagesByType)) {
      for (const f of files) {
        pages.push({ path: f, fullPath: f });
      }
    }
    return pages;
  }, [pagesByType]);

  const { pinned, tree } = useMemo(() => {
    const pinned: Array<{ path: string; fullPath: string }> = [];
    const rest: Array<{ path: string; fullPath: string }> = [];
    for (const p of allPages) {
      const name = p.path.split('/').pop()?.replace(/\.md$/, '') || '';
      if (name === 'index' || name === 'overview') {
        pinned.push(p);
      } else {
        rest.push(p);
      }
    }
    return { pinned, tree: buildTree(rest) };
  }, [allPages]);

  const filteredTree = useMemo(() => {
    if (!search) return tree;
    const q = search.toLowerCase();
    const filtered = allPages.filter((p) => {
      const name = p.path.split('/').pop()?.replace(/\.md$/, '') || '';
      if (name === 'index' || name === 'overview') return false;
      return p.path.toLowerCase().includes(q);
    });
    return buildTree(filtered);
  }, [tree, allPages, search]);

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

      {pinned.length > 0 && !search && pinned.map((node) => (
        <button
          key={node.path}
          onClick={() => onSelect(node.fullPath || node.path)}
          className={`w-full text-left px-2 py-1 text-sm truncate transition-colors flex items-center gap-1.5 ${
            selectedPage === (node.fullPath || node.path) ? 'bg-blue-600/30 text-blue-300' : 'text-slate-300 hover:bg-slate-700'
          }`}
          style={{ paddingLeft: '8px' }}
          title={node.fullPath || node.path}
        >
          <span className="text-xs">⭐</span>
          {node.path.split('/').pop()?.replace(/\.md$/, '')}
        </button>
      ))}

      {filteredTree.map((node) => (
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

      {tree.length === 0 && (
        <div className="px-3 py-4 text-center text-xs text-slate-500">
          {search ? 'No matching pages' : 'No pages found'}
        </div>
      )}
    </div>
  );
}
