import { useState, useEffect } from 'react';
import { useWikiStore } from '../stores/wikiStore';
import { api } from '../api';

interface FileTreeProps {
  onSelect?: (page: string) => void;
  currentWikiId?: string | null;
}

export function FileTree({ onSelect, currentWikiId }: FileTreeProps) {
  const { isMultiWikiMode } = useWikiStore();
  const [files, setFiles] = useState<Array<{ name: string; path: string; type: 'file' | 'dir' }>>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['wiki']));

  useEffect(() => {
    if (isMultiWikiMode && currentWikiId) {
      api.wiki.scoped.pages(currentWikiId).then(data => {
        const fileList = data.pages.map((p: string) => ({
          name: p.split('/').pop() || p,
          path: p,
          type: 'file' as const,
        }));
        setFiles(fileList);
        setExpanded(new Set());
      }).catch(() => {
        setFiles([]);
      });
    } else {
      setFiles([
        { name: 'wiki', path: 'wiki', type: 'dir' },
        { name: 'index.md', path: 'wiki/index.md', type: 'file' },
        { name: 'log.md', path: 'wiki/log.md', type: 'file' },
        { name: 'overview.md', path: 'wiki/overview.md', type: 'file' },
      ]);
    }
  }, [currentWikiId, isMultiWikiMode]);

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="text-sm">
      {files.map((f) => (
        <div key={f.path}>
          {f.type === 'dir' ? (
            <button
              onClick={() => toggle(f.path)}
              className="w-full text-left px-2 py-1 hover:bg-slate-700 flex items-center gap-1"
            >
              <span className="text-xs">
                {expanded.has(f.path) ? '▼' : '▶'}
              </span>
              <span className="text-slate-300">{f.name}</span>
            </button>
          ) : (
            <button
              onClick={() => onSelect?.(f.path)}
              className="w-full text-left px-2 py-1 pl-6 hover:bg-slate-700 text-slate-400"
            >
              {f.name}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}