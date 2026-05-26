import { useState, useEffect } from 'react';
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
}

export function SessionSidebar({ currentSessionId, onSelectSession, onNewChat }: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadSessions();
  }, []);

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

  const deleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await api.agent.deleteSession?.(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (currentSessionId === sessionId) {
        onNewChat();
      }
    } catch { /* silent */ }
  };

  const formatDate = (iso: string) => {
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
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-[var(--border)]">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium
            bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
        >
          <span>＋</span>
          <span>New Chat</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && sessions.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">
            Loading...
          </div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">
            No sessions yet
          </div>
        )}
        {sessions.map((session) => (
          <div
            key={session.id}
            onClick={() => onSelectSession(session.id)}
            className={`
              group relative px-3 py-2.5 cursor-pointer border-b border-[var(--border)] transition-colors
              ${session.id === currentSessionId
                ? 'bg-[var(--accent)]/10 border-l-2 border-l-[var(--accent)]'
                : 'hover:bg-[var(--bg-tertiary)]'
              }
            `}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0 pr-6">
                <div className="text-sm font-medium truncate text-[var(--text-primary)]">
                  {session.id.slice(0, 8)}
                </div>
                <div className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {formatDate(session.updated_at || session.created_at)}
                </div>
              </div>
            </div>
            <button
              onClick={(e) => deleteSession(e, session.id)}
              className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100
                text-xs text-[var(--text-secondary)] hover:text-red-400 transition-opacity p-1"
              title="Delete session"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}