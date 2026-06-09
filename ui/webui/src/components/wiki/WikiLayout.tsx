import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { FileText, BarChart3, Lightbulb, Bot, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { Notifications } from './Notifications';
import { HealthStatus } from './HealthStatus';
import { WikiSelector } from './WikiSelector';
import { CrossWikiSearch } from './CrossWikiSearch';
import { WikiManager } from './WikiManager';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

export function WikiLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showManager, setShowManager] = useState(false);
  const { loadWikis } = useWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-2.5 w-full px-3 py-2.5 rounded-lg text-sm transition-colors relative',
      isActive
        ? 'bg-primary/15 text-primary font-medium'
        : 'text-muted-foreground hover:bg-muted hover:text-foreground',
    );

  return (
    <div className="flex h-screen bg-background text-foreground">
      {sidebarOpen && (
        <aside className="w-60 bg-sidebar border-r border-sidebar-border flex flex-col shrink-0">
          <div className="p-4 border-b border-sidebar-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
                <span className="text-primary font-bold text-sm">W</span>
              </div>
              <h1 className="text-sm font-semibold text-sidebar-foreground">llmwikify</h1>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-muted transition-colors"
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
          </div>

          <WikiSelector onOpenManager={() => setShowManager(true)} />

          <nav className="p-2 space-y-0.5 overflow-y-auto flex-1">
            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider px-3 py-2">Wiki</div>
            <NavLink to="/edit" className={linkClass} end>
              <FileText className="w-4 h-4 shrink-0" />
              <span>Editor</span>
            </NavLink>
            <NavLink to="/dashboard" className={linkClass}>
              <BarChart3 className="w-4 h-4 shrink-0" />
              <span>Dashboard</span>
            </NavLink>
            <NavLink to="/insights" className={linkClass}>
              <Lightbulb className="w-4 h-4 shrink-0" />
              <span>Insights</span>
            </NavLink>

            <div className="border-t border-sidebar-border my-2" />
            <NavLink to="/agent" className={linkClass}>
              <Bot className="w-4 h-4 shrink-0" />
              <span>Agent</span>
            </NavLink>
          </nav>

          <HealthStatus />
        </aside>
      )}

      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          className="absolute top-4 left-4 z-10 p-2 bg-card border border-border rounded-lg shadow-sm hover:bg-muted transition-colors"
        >
          <PanelLeftOpen className="w-4 h-4 text-muted-foreground" />
        </button>
      )}

      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-border flex items-center gap-3 bg-background">
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
