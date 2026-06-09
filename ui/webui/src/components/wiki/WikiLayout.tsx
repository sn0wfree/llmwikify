import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { Notifications } from './Notifications';
import { HealthStatus } from './HealthStatus';
import { WikiSelector } from './WikiSelector';
import { CrossWikiSearch } from './CrossWikiSearch';
import { WikiManager } from './WikiManager';
import { useWikiStore } from '../../stores/wikiStore';

export function WikiLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showManager, setShowManager] = useState(false);
  const { loadWikis } = useWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

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
            <h1 className="text-lg font-bold text-[var(--accent)]">llmwikify</h1>
            <button
              onClick={() => setSidebarOpen(false)}
              className="text-[var(--text-secondary)] hover:text-[var(--accent)]"
            >
              ×
            </button>
          </div>

          <WikiSelector onOpenManager={() => setShowManager(true)} />

          <nav className="p-2 space-y-1 overflow-y-auto flex-1">
            <div className="text-xs text-[var(--text-secondary)] px-3 py-1 mt-2">Wiki</div>
            <NavLink to="/edit" className={linkClass} end>
              <span className="ml-1">Editor</span>
            </NavLink>
            <NavLink to="/dashboard" className={linkClass}>
              <span className="ml-1">Dashboard</span>
            </NavLink>
            <NavLink to="/insights" className={linkClass}>
              <span className="ml-1">Insights</span>
            </NavLink>

            <div className="border-t border-[var(--border)] my-2" />
            <NavLink to="/agent" className={linkClass}>
              <span className="ml-1">→ Agent</span>
            </NavLink>
          </nav>

          <HealthStatus />
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
        <div className="p-3 border-b border-[var(--border)] flex items-center gap-3">
          <CrossWikiSearch />
          <Notifications />
        </div>
        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>

      {showManager && <WikiManager onClose={() => setShowManager(false)} />}
    </div>
  );
}
