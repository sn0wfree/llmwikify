import { useState, useEffect, useCallback } from 'react';
import { Hash, Plus, Trash2, MessageSquare } from 'lucide-react';
import { api } from '../api';

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
const COLLAPSED_WIDTH = 64;
const EXPANDED_WIDTH = 240;

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

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

  useEffect(() => {
    if (!collapsed) loadSessions();
  }, [collapsed, refreshKey]);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(collapsed));
    } catch {
      /* private browsing */
    }
  }, [collapsed]);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await api.agent.sessions();
      setSessions(data.sessions as SessionInfo[]);
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
      } catch {
        /* silent */
      }
    },
    [currentSessionId, onNewChat],
  );

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => !c);
  }, []);

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  return (
    <div
      className="flex flex-col h-full border-r border-[var(--border)] bg-[var(--bg-secondary)]/60 backdrop-blur-sm transition-[width] duration-200"
      style={{ width }}
      aria-label="Session sidebar"
    >
      <div
        className={`p-2 border-b border-[var(--border)] flex items-center ${
          collapsed ? 'justify-center' : 'justify-between'
        }`}
      >
        {collapsed ? (
          <button
            onClick={toggleCollapsed}
            className="p-1.5 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
            title="Expand sidebar"
            aria-label="Expand sidebar"
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        ) : (
          <>
            <button
              onClick={onNewChat}
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-sm font-medium
                bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
              title="Start a new chat"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New Chat</span>
            </button>
            <button
              onClick={toggleCollapsed}
              className="p-1.5 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors ml-1"
              title="Collapse sidebar"
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

      {collapsed ? (
        <div className="flex-1 overflow-y-auto py-2 flex flex-col items-center gap-1">
          {sessions.slice(0, 20).map((session, idx) => {
            const isActive = session.id === currentSessionId;
            return (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                title={formatDate(session.updated_at || session.created_at)}
                className={`relative w-10 h-10 rounded flex items-center justify-center text-xs font-mono transition-colors ${
                  isActive
                    ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]/60 hover:text-[var(--text-primary)]'
                }`}
              >
                <Hash className="w-3.5 h-3.5" />
                <span className="absolute -bottom-0.5 -right-0.5 text-[9px] font-sans text-[var(--text-secondary)]">
                  {idx + 1}
                </span>
                {isActive && <span className="nav-rail-active-indicator" />}
              </button>
            );
          })}
          {sessions.length === 0 && !loading && (
            <div className="text-[10px] text-[var(--text-secondary)] mt-4 writing-vertical">
              No sessions
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          {loading && sessions.length === 0 && (
            <div className="p-3 text-xs text-[var(--text-secondary)] text-center">Loading...</div>
          )}
          {!loading && sessions.length === 0 && (
            <div className="p-3 text-xs text-[var(--text-secondary)] text-center">No sessions yet</div>
          )}
          {sessions.map((session) => {
            const isActive = session.id === currentSessionId;
            return (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`group relative px-3 py-2.5 cursor-pointer border-b border-[var(--border)]/40 transition-colors ${
                  isActive
                    ? 'bg-[var(--accent)]/10 text-[var(--text-primary)]'
                    : 'hover:bg-[var(--bg-tertiary)]/40 text-[var(--text-primary)]'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2 min-w-0 pr-6">
                    <Hash className="w-3 h-3 text-[var(--text-secondary)] shrink-0" />
                    <span className="text-sm font-mono truncate">
                      {session.id.slice(0, 8)}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-[var(--text-secondary)] mt-0.5 ml-5">
                  {formatDate(session.updated_at || session.created_at)}
                </div>
                {isActive && <span className="nav-rail-active-indicator" />}
                <button
                  onClick={(e) => deleteSession(e, session.id)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100
                    text-[var(--text-secondary)] hover:text-[var(--error)] transition-opacity p-1 rounded hover:bg-[var(--bg-tertiary)]/60"
                  title="Delete session"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
