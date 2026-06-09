import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { MessageSquare, Search, Zap, CheckSquare, Settings, ArrowLeft, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { WikiSelector } from '../wiki/WikiSelector';
import { Badge } from '../ui/badge';
import { Backdrop } from './Backdrop';
import { useWikiStore } from '../../stores/wikiStore';
import { api } from '../../api';
import { cn } from '@/lib/utils';

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
      } catch { /* silent */ }
    };
    fetchBadges();
    const interval = setInterval(fetchBadges, 30000);
    return () => clearInterval(interval);
  }, [currentWikiId]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm transition-colors relative',
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
                <span className="text-primary font-bold text-sm">A</span>
              </div>
              <h1 className="text-sm font-semibold text-sidebar-foreground">Agent</h1>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-muted transition-colors"
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
          </div>

          <WikiSelector />

          <nav className="p-2 space-y-0.5 overflow-y-auto flex-1">
            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider px-3 py-2">Agent</div>
            <NavLink to="/agent/chat" className={linkClass} end>
              <MessageSquare className="w-4 h-4 shrink-0" />
              <span>Chat</span>
            </NavLink>
            <NavLink to="/agent/research" className={linkClass}>
              <Search className="w-4 h-4 shrink-0" />
              <span>Research</span>
            </NavLink>
            <NavLink to="/agent/autoresearch" className={linkClass}>
              <Zap className="w-4 h-4 shrink-0" />
              <span>AutoResearch</span>
            </NavLink>

            <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider px-3 py-2 mt-3">System</div>
            <NavLink to="/agent/tasks" className={linkClass}>
              <CheckSquare className="w-4 h-4 shrink-0" />
              <span>Tasks</span>
            </NavLink>
            <NavLink to="/agent/settings" className={linkClass}>
              <Settings className="w-4 h-4 shrink-0" />
              <span>Settings</span>
            </NavLink>

            <div className="border-t border-sidebar-border my-2" />
            <NavLink to="/" className={linkClass}>
              <ArrowLeft className="w-4 h-4 shrink-0" />
              <span>Wiki</span>
            </NavLink>

            {(badges.confirmations > 0 || badges.proposals > 0 || badges.notifications > 0) && (
              <>
                <div className="border-t border-sidebar-border my-2" />
                <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider px-3 py-2">Activity</div>
                <div className="px-3 py-1 text-sm text-muted-foreground flex items-center justify-between">
                  <span>Confirmations</span>
                  <Badge variant="destructive">{badges.confirmations}</Badge>
                </div>
                <div className="px-3 py-1 text-sm text-muted-foreground flex items-center justify-between">
                  <span>Proposals</span>
                  <Badge variant="outline">{badges.proposals}</Badge>
                </div>
                <div className="px-3 py-1 text-sm text-muted-foreground flex items-center justify-between">
                  <span>Notifications</span>
                  <Badge>{badges.notifications}</Badge>
                </div>
              </>
            )}
          </nav>
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
        <Backdrop />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
