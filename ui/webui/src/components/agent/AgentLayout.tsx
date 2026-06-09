import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { WikiSelector } from '../wiki/WikiSelector';
import { Badge } from '../ui/Badge';
import { Backdrop } from './Backdrop';
import { useWikiStore } from '../../stores/wikiStore';
import { api } from '../../api';

interface BadgeCounts {
  confirmations: number;
  proposals: number;
  notifications: number;
}

export function AgentLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [badges, setBadges] = useState<BadgeCounts>({ confirmations: 0, proposals: 0, notifications: 0 });
  const { loadWikis, currentWikiId } = useWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  useEffect(() => {
    const fetchBadges = async () => {
      try {
        const status = await api.agent.status(currentWikiId || undefined);
        const proposalsCount = Object.values(status.dream_proposals || {}).reduce(
          (a: number, b) => a + (Number(b) || 0), 0
        ) as number;
        setBadges({
          confirmations: status.pending_confirmations || 0,
          proposals: proposalsCount || 0,
          notifications: status.unread_notifications || 0,
        });
      } catch {
        /* silent */
      }
    };
    fetchBadges();
    const interval = setInterval(fetchBadges, 30000);
    return () => clearInterval(interval);
  }, [currentWikiId]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `w-full text-left px-3 py-2 rounded text-sm transition-colors relative ${
      isActive
        ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
        : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
    }`;

  return (
    <div className="flex h-screen bg-[var(--bg-primary)] text-[var(--text-primary)]">
      {sidebarOpen && (
        <aside className="w-64 bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col">
          <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
            <h1 className="text-lg font-bold text-[var(--accent)]">llmwikify Agent</h1>
            <button
              onClick={() => setSidebarOpen(false)}
              className="text-[var(--text-secondary)] hover:text-[var(--accent)]"
            >
              ×
            </button>
          </div>

          <WikiSelector />

          <nav className="p-2 space-y-1 overflow-y-auto flex-1">
            <div className="text-xs text-[var(--text-secondary)] px-3 py-1 mt-2">Agent</div>
            <NavLink to="/agent/chat" className={linkClass} end>
              <span className="ml-1">Agent Chat</span>
            </NavLink>
            <NavLink to="/agent/research" className={linkClass}>
              <span className="ml-1">Research</span>
            </NavLink>
            <NavLink to="/agent/autoresearch" className={linkClass}>
              <span className="ml-1">AutoResearch</span>
            </NavLink>

            <div className="text-xs text-[var(--text-secondary)] px-3 py-1 mt-3">System</div>
            <NavLink to="/agent/tasks" className={linkClass}>
              <span className="ml-1">Tasks</span>
            </NavLink>
            <NavLink to="/agent/settings" className={linkClass}>
              <span className="ml-1">LLM Settings</span>
            </NavLink>

            <div className="border-t border-[var(--border)] my-2" />
            <NavLink to="/" className={linkClass}>
              <span className="ml-1">← Wiki</span>
            </NavLink>

            <div className="border-t border-[var(--border)] my-2" />
            <div className="text-xs text-[var(--text-secondary)] px-3 py-1">Activity</div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Confirmations: <Badge variant="error">{badges.confirmations}</Badge>
            </div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Proposals: <Badge variant="warning">{badges.proposals}</Badge>
            </div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Notifications: <Badge>{badges.notifications}</Badge>
            </div>
          </nav>
        </aside>
      )}

      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          className="absolute top-4 left-4 z-10 px-3 py-1 bg-[var(--bg-secondary)] rounded text-sm"
        >
          ☰ Menu
        </button>
      )}

      <main className="flex-1 flex flex-col overflow-hidden">
        <Backdrop />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
