import { useState, useMemo, useEffect } from 'react';
import {
  Search, ChevronRight, Folder, FolderOpen,
  FileText, Star, X, BookOpen, Hash,
} from 'lucide-react';
import { cn } from '@/lib/utils';

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
  dirType?: string;
}

const TYPE_COLOR_VARS = [
  '--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5',
];

const TYPE_LABELS: Record<string, string> = {
  sources: 'Sources',
  entities: 'Entities',
  concepts: 'Concepts',
  papers: 'Papers',
  claims: 'Claims',
  root: 'Root',
  comparisons: 'Comparisons',
  synthesis: 'Synthesis',
  research: 'Research',
  factors: 'Factors',
  company: 'Company',
  industry: 'Industry',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  yearly: 'Yearly',
};

function countNodes(node: TreeNode): number {
  if (node.type === 'file') return 1;
  return node.children.reduce((sum, child) => sum + countNodes(child), 0);
}

function buildTree(pages: Array<{ path: string; fullPath: string; dirType: string }>): TreeNode[] {
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
          dirType: i === 0 ? page.dirType : undefined,
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

function getTypeColorVar(dirType: string | undefined, allTypes: string[]): string {
  if (!dirType || !allTypes.includes(dirType)) return '--muted-foreground';
  const idx = allTypes.indexOf(dirType);
  return TYPE_COLOR_VARS[idx % TYPE_COLOR_VARS.length];
}

interface TreeNodeComponentProps {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
  selectedPage: string | null;
  allTypes: string[];
}

function TreeNodeComponent({
  node, depth, expanded, onToggle, onSelect, selectedPage, allTypes,
}: TreeNodeComponentProps) {
  const isExpanded = expanded.has(node.path);
  const isSelected = node.type === 'file' && node.fullPath === selectedPage;
  const colorVar = getTypeColorVar(node.dirType, allTypes);

  if (node.type === 'directory') {
    const childCount = countNodes(node);
    return (
      <div>
        <button
          onClick={() => onToggle(node.path)}
          className={cn(
            'group w-full text-left px-2 py-1 flex items-center gap-1.5 transition-colors rounded-md',
            'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
          )}
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
        >
          <ChevronRight
            className={cn(
              'w-3 h-3 text-muted-foreground/60 transition-transform duration-150 shrink-0',
              isExpanded && 'rotate-90',
            )}
          />
          {isExpanded ? (
            <FolderOpen className="w-3.5 h-3.5 shrink-0" style={{ color: `var(${colorVar})` }} />
          ) : (
            <Folder className="w-3.5 h-3.5 shrink-0" style={{ color: `var(${colorVar})` }} />
          )}
          <span className="text-xs font-medium flex-1 truncate">{node.name}</span>
          <span className="text-[10px] text-muted-foreground/60 font-mono tabular-nums">
            {childCount}
          </span>
        </button>
        {isExpanded && node.children.map((child) => (
          <TreeNodeComponent
            key={child.path}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            onToggle={onToggle}
            onSelect={onSelect}
            selectedPage={selectedPage}
            allTypes={allTypes}
          />
        ))}
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelect(node.fullPath || node.path)}
      className={cn(
        'group w-full text-left px-2 py-1 text-xs truncate transition-all rounded-md',
        'flex items-center gap-1.5',
        isSelected
          ? 'bg-primary/15 text-primary font-medium'
          : 'text-foreground/80 hover:bg-white/[0.04] hover:text-foreground',
      )}
      style={{ paddingLeft: `${depth * 14 + 22}px` }}
      title={node.fullPath || node.path}
    >
      <FileText className={cn(
        'w-3 h-3 shrink-0',
        isSelected ? 'text-primary' : 'text-muted-foreground/60',
      )} />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

export function PageTree({ pagesByType, selectedPage, onSelect }: PageTreeProps) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Sort types for stable ordering
  const sortedTypes = useMemo(() => {
    return Object.keys(pagesByType).sort();
  }, [pagesByType]);

  const allTypes = sortedTypes;

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

  const pagesByTypeLabeled = useMemo(() => {
    const result: Array<{ type: string; pages: string[] }> = [];
    for (const t of sortedTypes) {
      result.push({ type: t, pages: pagesByType[t] || [] });
    }
    return result;
  }, [pagesByType, sortedTypes]);

  const filtered = useMemo(() => {
    if (!search) return null;
    const q = search.toLowerCase();
    const out: Array<{ type: string; pages: string[] }> = [];
    for (const { type, pages } of pagesByTypeLabeled) {
      const matched = pages.filter((p) => p.toLowerCase().includes(q));
      if (matched.length > 0) out.push({ type, pages: matched });
    }
    return out;
  }, [pagesByTypeLabeled, search]);

  const pinned = useMemo(() => {
    const out: string[] = [];
    for (const pages of Object.values(pagesByType)) {
      for (const p of pages) {
        const name = p.split('/').pop()?.replace(/\.md$/, '') || '';
        if (name === 'index' || name === 'overview') {
          out.push(p);
        }
      }
    }
    return out;
  }, [pagesByType]);

  const toggleDir = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const totalPages = Object.values(pagesByType).reduce((s, p) => s + p.length, 0);

  return (
    <div className="text-sm">
      {/* Search */}
      <div className="px-2.5 py-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            placeholder="Filter pages…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={cn(
              'w-full pl-7 pr-7 py-1.5 text-xs rounded-md',
              'bg-white/[0.04] border border-border/40',
              'text-foreground placeholder:text-muted-foreground',
              'focus:outline-none focus:border-primary/40 focus:bg-white/[0.06]',
              'transition-colors',
            )}
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-muted-foreground hover:text-foreground"
              aria-label="Clear"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
        <div className="mt-1.5 text-[10px] text-muted-foreground/70 px-1 flex items-center gap-1.5">
          <Hash className="w-2.5 h-2.5" />
          <span>{totalPages} {totalPages === 1 ? 'page' : 'pages'}</span>
        </div>
      </div>

      {/* Pinned */}
      {pinned.length > 0 && !search && (
        <div className="mb-1">
          {pinned.map((p) => {
            const isActive = p === selectedPage;
            const name = p.split('/').pop()?.replace(/\.md$/, '') || '';
            return (
              <button
                key={p}
                onClick={() => onSelect(p)}
                className={cn(
                  'group w-full text-left px-2 py-1 text-xs truncate transition-all rounded-md mx-1.5',
                  'flex items-center gap-1.5',
                  isActive
                    ? 'bg-primary/15 text-primary font-medium'
                    : 'text-foreground/85 hover:bg-white/[0.04] hover:text-foreground',
                )}
                style={{ width: 'calc(100% - 12px)' }}
                title={p}
              >
                <Star className={cn('w-3 h-3 shrink-0', isActive ? 'text-primary fill-primary' : 'text-warning/70 fill-warning/30')} />
                <span className="truncate">{name}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Tree or filtered results */}
      {filtered ? (
        <FilteredView data={filtered} selectedPage={selectedPage} onSelect={onSelect} />
      ) : (
        <div className="space-y-0.5">
          {pagesByTypeLabeled.map(({ type, pages }) => {
            if (pages.length === 0) return null;
            const isExpanded = expanded.has(type) || search.length > 0;
            const colorVar = getTypeColorVar(type, allTypes);
            const tree = buildTree(pages.map((p) => ({ path: p, fullPath: p, dirType: type })));
            return (
              <div key={type}>
                <button
                  onClick={() => toggleDir(type)}
                  className={cn(
                    'group w-full text-left px-2 py-1 flex items-center gap-1.5',
                    'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
                    'transition-colors rounded-md mx-1.5',
                  )}
                  style={{ width: 'calc(100% - 12px)' }}
                >
                  <ChevronRight
                    className={cn(
                      'w-3 h-3 text-muted-foreground/60 transition-transform duration-150 shrink-0',
                      isExpanded && 'rotate-90',
                    )}
                  />
                  <Folder className="w-3.5 h-3.5 shrink-0" style={{ color: `var(${colorVar})` }} />
                  <span className="text-[10px] font-semibold uppercase tracking-[0.08em] flex-1 truncate">
                    {TYPE_LABELS[type] || type}
                  </span>
                  <span className="text-[10px] text-muted-foreground/60 font-mono tabular-nums">
                    {pages.length}
                  </span>
                </button>
                {isExpanded && tree.map((node) => (
                  <TreeNodeComponent
                    key={node.path}
                    node={node}
                    depth={0}
                    expanded={expanded}
                    onToggle={toggleDir}
                    onSelect={onSelect}
                    selectedPage={selectedPage}
                    allTypes={allTypes}
                  />
                ))}
              </div>
            );
          })}
        </div>
      )}

      {totalPages === 0 && !search && (
        <div className="px-3 py-8 text-center">
          <BookOpen className="w-6 h-6 mx-auto text-muted-foreground/40 mb-2" />
          <div className="text-xs text-muted-foreground">No pages found</div>
        </div>
      )}

      {search && filtered && filtered.length === 0 && (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground">
          No matches for "{search}"
        </div>
      )}
    </div>
  );
}

function FilteredView({
  data, selectedPage, onSelect,
}: {
  data: Array<{ type: string; pages: string[] }>;
  selectedPage: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <div className="space-y-1">
      {data.map(({ type, pages }) => {
        const colorVar = getTypeColorVar(type, data.map((d) => d.type));
        return (
          <div key={type}>
            <div className="px-3 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.08em] flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: `var(${colorVar})` }} />
              {TYPE_LABELS[type] || type}
              <span className="text-muted-foreground/60 ml-auto">{pages.length}</span>
            </div>
            {pages.map((p) => {
              const name = p.split('/').pop()?.replace(/\.md$/, '') || '';
              const isActive = p === selectedPage;
              return (
                <button
                  key={p}
                  onClick={() => onSelect(p)}
                  className={cn(
                    'group w-full text-left px-2.5 py-1 text-xs truncate transition-all rounded-md mx-1.5',
                    'flex items-center gap-1.5',
                    isActive
                      ? 'bg-primary/15 text-primary font-medium'
                      : 'text-foreground/85 hover:bg-white/[0.04] hover:text-foreground',
                  )}
                  style={{ width: 'calc(100% - 12px)' }}
                >
                  <FileText className={cn('w-3 h-3 shrink-0', isActive ? 'text-primary' : 'text-muted-foreground/60')} />
                  <span className="truncate">{name}</span>
                </button>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
