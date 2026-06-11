/**
 * PaperSessionSidebar — left sidebar listing paper extraction sessions.
 *
 * Mirrors reproduction/SessionSidebar pattern:
 * - Polls /api/paper/list every 5s while a session is selected
 * - Click a row to switch; "+ 新建" button to deselect (enter Form mode)
 */

import { useCallback, useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { Plus, FileText, Trash2 } from 'lucide-react';
import {
  PAPER_STATUS_LABELS,
  listPaperSessions,
  deletePaperSession,
  type PaperSession,
} from '../../lib/paper-api';

interface PaperSessionSidebarProps {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

function formatRelativeTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

function truncate(s: string, n: number): string {
  if (!s) return '';
  return s.length <= n ? s : s.slice(0, n) + '…';
}

export function PaperSessionSidebar({ selectedId, onSelect }: PaperSessionSidebarProps) {
  const [sessions, setSessions] = useState<PaperSession[]>([]);
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPaperSessions();
      setSessions(data.sessions || []);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  useEffect(() => {
    if (!selectedId) return;
    const interval = setInterval(loadSessions, 5000);
    return () => clearInterval(interval);
  }, [selectedId, loadSessions]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await deletePaperSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (selectedId === sessionId) onSelect(null);
    } catch { /* ignore */ }
  };

  return (
    <div className="flex flex-col h-full min-h-0 border-r border-border">
      <div className="p-3 border-b border-border">
        <button
          onClick={() => onSelect(null)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium
            bg-primary text-white hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>新建提取</span>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && sessions.length === 0 ? (
          <div className="p-3 text-xs text-muted-foreground text-center">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="p-3 text-xs text-muted-foreground text-center">
            <div className="mb-1">暂无历史会话</div>
            <div className="text-[10px] opacity-70">点上方"新建"开始提取论文</div>
          </div>
        ) : (
          sessions.map((s) => {
            const status = PAPER_STATUS_LABELS[s.status] || PAPER_STATUS_LABELS.error;
            return (
              <div key={s.id} className="relative group">
                <button
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    'w-full text-left px-3 py-2.5 border-b border-border transition-colors',
                    selectedId === s.id
                      ? 'bg-primary/10'
                      : 'hover:bg-muted/50'
                  )}
                >
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={cn('text-[11px]', status.color)}>{status.icon}</span>
                    <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
                    <span className="text-xs font-medium truncate">{s.paper_id}</span>
                  </div>
                  <div className="text-[10px] text-muted-foreground font-mono truncate">
                    {s.source_type} · {truncate(s.source_ref, 24)}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1.5">
                    <span>{formatRelativeTime(s.created_at)}</span>
                    {s.error && (
                      <span className="text-red-400 truncate" title={s.error}>
                        · {truncate(s.error, 16)}
                      </span>
                    )}
                  </div>
                </button>
                <button
                  onClick={(e) => handleDelete(e, s.id)}
                  className={cn(
                    'absolute right-1.5 top-1/2 -translate-y-1/2',
                    'opacity-0 group-hover:opacity-100 transition-opacity',
                    'text-muted-foreground hover:text-destructive p-1 rounded hover:bg-white/[0.06]',
                  )}
                  title="删除会话"
                  aria-label="删除会话"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
