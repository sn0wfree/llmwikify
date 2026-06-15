import { useState, useEffect, useCallback, useMemo } from 'react';
import { Hash, Plus, Trash2, MessageSquare, Search, X } from 'lucide-react';
import { api } from '../../api';
import { cn } from '@/lib/utils';

interface SessionInfo {
  id: string;
  wiki_id: string | null;
  created_at: string;
  updated_at: string;
}

interface SessionSidebarProps {
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  refreshKey?: number;
}

const COLLAPSED_KEY = 'chat-sidebar-collapsed';
const COLLAPSED_WIDTH = 56;
const EXPANDED_WIDTH = 280;

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

function dayBucket(iso: string): 'today' | 'yesterday' | 'thisWeek' | 'older' {
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const weekAgo = new Date(startOfToday);
  weekAgo.setDate(weekAgo.getDate() - 7);

  if (d >= startOfToday) return 'today';
  if (d >= startOfYesterday) return 'yesterday';
  if (d >= weekAgo) return 'thisWeek';
  return 'older';
}

const BUCKET_LABELS: Record<ReturnType<typeof dayBucket>, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  thisWeek: 'Previous 7 days',
  older: 'Older',
};

const BUCKET_ORDER: Array<ReturnType<typeof dayBucket>> = [
  'today', 'yesterday', 'thisWeek', 'older',
];

export function SessionSidebar({ currentSessionId, onSelectSession, onNewChat, refreshKey }: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!collapsed) loadSessions();
  }, [collapsed, refreshKey]);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(collapsed));
    } catch { /* private browsing */ }
  }, [collapsed]);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await api.agent.sessions();
      const list = (data.sessions as SessionInfo[]) || [];
      list.sort((a, b) =>
        new Date(b.updated_at || b.created_at).getTime() -
        new Date(a.updated_at || a.created_at).getTime()
      );
      setSessions(list);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  };

  const deleteSession = useCallback(
    async (e: React.MouseEvent, sessionId: string) => {
      e.stopPropagation();
      try {
        await api.agent.deleteSession?.(sessionId);
        setSessions((prev) => prev.filter((s) => s.id !== sessionId));
        if (currentSessionId === sessionId) {
          onNewChat();
        }
      } catch (error) {
        console.error('Failed to delete chat session', error);
      }
    },
    [currentSessionId, onNewChat],
  );

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => !c);
  }, []);

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  const filtered = useMemo(() => {
    if (!debouncedQuery.trim()) return sessions;
    const q = debouncedQuery.toLowerCase();
    return sessions.filter((s) => s.id.toLowerCase().includes(q));
  }, [sessions, debouncedQuery]);

  const grouped = useMemo(() => {
    const buckets: Record<ReturnType<typeof dayBucket>, SessionInfo[]> = {
      today: [], yesterday: [], thisWeek: [], older: [],
    };
    for (const s of filtered) {
      buckets[dayBucket(s.updated_at || s.created_at)].push(s);
    }
    return buckets;
  }, [filtered]);

  return (
    <div
      className={cn(
        'flex flex-col h-full border-r border-border shrink-0',
        'transition-[width] duration-200 ease-out',
        collapsed ? 'bg-card/40' : 'bg-card/40 backdrop-blur-sm',
      )}
      style={{ width }}
      aria-label="Session sidebar"
    >
      {/* Header */}
      <div className={cn('p-2 border-b border-border/50 flex items-center gap-1.5', collapsed && 'justify-center')}>
        {collapsed ? (
          <button
            onClick={toggleCollapsed}
            className="p-1.5 rounded-md hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors"
            title="Expand"
            aria-label="Expand sidebar"
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        ) : (
          <>
            <button
              onClick={onNewChat}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium',
                'bg-primary text-primary-foreground hover:brightness-110 transition-all',
                'shadow-soft',
              )}
              title="Start a new chat"
            >
              <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />
              <span>New chat</span>
            </button>
            <button
              onClick={toggleCollapsed}
              className="p-1.5 rounded-md hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-colors"
              title="Collapse"
              aria-label="Collapse sidebar"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
          </>
        )}
      </div>

      {/* Search */}
      {!collapsed && (
        <div className="px-2 pt-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search sessions…"
              className="w-full pl-7 pr-7 py-1.5 text-xs bg-white/[0.04] border border-border/50 rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 focus:bg-white/[0.06] transition-colors"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-muted-foreground hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Sessions */}
      {collapsed ? (
        <div className="flex-1 overflow-y-auto py-2 flex flex-col items-center gap-1">
          {sessions.slice(0, 20).map((session, idx) => {
            const isActive = session.id === currentSessionId;
            return (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                title={formatRelative(session.updated_at || session.created_at)}
                className={cn(
                  'relative w-9 h-9 rounded-md flex items-center justify-center text-[10px] font-mono transition-all',
                  isActive
                    ? 'bg-primary/15 text-primary shadow-soft'
                    : 'text-muted-foreground hover:bg-white/[0.06] hover:text-foreground',
                )}
              >
                <Hash className="w-3.5 h-3.5" />
                <span className="absolute -bottom-0.5 -right-0.5 text-[8px] font-sans text-muted-foreground">
                  {idx + 1}
                </span>
                {isActive && <span className="nav-rail-active-indicator" />}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto py-1">
          {loading && sessions.length === 0 && (
            <div className="p-3 text-xs text-muted-foreground text-center">Loading…</div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="p-6 text-center">
              <div className="text-xs text-muted-foreground">
                {debouncedQuery ? 'No matches' : 'No sessions yet'}
              </div>
              {!debouncedQuery && (
                <p className="text-[10px] text-muted-foreground/70 mt-1">
                  Start a new chat to begin
                </p>
              )}
            </div>
          )}

          {BUCKET_ORDER.map((bucket) => {
            const items = grouped[bucket];
            if (items.length === 0) return null;
            return (
              <div key={bucket} className="mb-1">
                <div className="px-3 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] flex items-center justify-between">
                  <span>{BUCKET_LABELS[bucket]}</span>
                  <span className="text-muted-foreground/60 tabular-nums">{items.length}</span>
                </div>
                {items.map((session) => {
                  const isActive = session.id === currentSessionId;
                  return (
                    <div
                      key={session.id}
                      onClick={() => onSelectSession(session.id)}
                      className={cn(
                        'group relative px-3 py-2 cursor-pointer transition-colors mx-1 rounded-md',
                        isActive
                          ? 'bg-primary/12 text-foreground'
                          : 'hover:bg-white/[0.04] text-foreground/85',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <Hash className={cn(
                            'w-3 h-3 shrink-0 transition-colors',
                            isActive ? 'text-primary' : 'text-muted-foreground',
                          )} />
                          <span className="text-xs font-mono truncate">
                            {session.id.slice(0, 8)}
                          </span>
                        </div>
                        <span className="text-[10px] text-muted-foreground shrink-0 tabular-nums">
                          {formatRelative(session.updated_at || session.created_at)}
                        </span>
                      </div>
                      {isActive && <span className="nav-rail-active-indicator" />}
                      <button
                        onClick={(e) => deleteSession(e, session.id)}
                        className={cn(
                          'absolute right-1.5 top-1/2 -translate-y-1/2',
                          'opacity-0 group-hover:opacity-100 transition-opacity',
                          'text-muted-foreground hover:text-destructive p-1 rounded hover:bg-white/[0.06]',
                        )}
                        title="Delete session"
                        aria-label="Delete session"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
