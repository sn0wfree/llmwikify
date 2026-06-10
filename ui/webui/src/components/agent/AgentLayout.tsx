import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  MessageSquare, Search, CheckSquare, Settings, ArrowLeft,
  PanelLeftClose, PanelLeftOpen, Sparkles, Bot, Activity,
  Beaker,
} from 'lucide-react';
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

const NAV_PRIMARY = [
  { to: '/agent/chat', label: 'Chat', icon: MessageSquare },
  { to: '/agent/autoresearch', label: 'Research', icon: Search },
  { to: '/agent/reproduction', label: 'Reproduction', icon: Beaker },
] as const;

const NAV_SECONDARY = [
  { to: '/agent/tasks', label: 'Tasks', icon: CheckSquare },
  { to: '/agent/settings', label: 'Settings', icon: Settings },
] as const;

export function AgentLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [badges, setBadges] = useState<BadgeCounts>({ confirmations: 0, proposals: 0, notifications: 0 });
  const { loadWikis, currentWikiId, wikis } = useWikiStore();

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
      'group relative flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm transition-all duration-200',
      isActive
        ? 'bg-primary/12 text-foreground font-medium'
        : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
    );

  const totalActivity = badges.confirmations + badges.proposals + badges.notifications;
  const currentWiki = wikis.find((w) => w.id === currentWikiId);

  return (
    <div className="flex h-screen bg-background text-foreground relative">
      {sidebarOpen && (
        <aside
          className="w-64 shrink-0 flex flex-col border-r border-sidebar-border glass"
          style={{ background: 'color-mix(in srgb, var(--sidebar) 75%, transparent)' }}
        >
          {/* Brand */}
          <div className="px-4 py-4 flex items-center justify-between border-b border-sidebar-border/50">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="relative shrink-0">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center shadow-soft">
                  <Sparkles className="w-4 h-4 text-primary-foreground" strokeWidth={2.5} />
                </div>
                <div className="absolute -inset-0.5 rounded-lg bg-gradient-to-br from-primary/40 to-accent/0 blur-md -z-10 opacity-60" />
              </div>
              <div className="min-w-0">
                <h1 className="text-sm font-semibold text-sidebar-foreground leading-none tracking-tight">
                  llmwikify
                </h1>
                <p className="text-[10px] text-muted-foreground mt-0.5 leading-none">
                  Agent workspace
                </p>
              </div>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-white/[0.06] transition-colors"
              aria-label="Collapse sidebar"
            >
              <PanelLeftClose className="w-3.5 h-3.5" />
            </button>
          </div>

          <WikiSelector />

          {/* Primary nav */}
          <nav className="px-2 pt-2 space-y-0.5">
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5">
              Workspace
            </div>
            {NAV_PRIMARY.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass} end={to === '/agent/chat'}>
                {({ isActive }) => (
                  <>
                    <Icon className={cn('w-4 h-4 shrink-0 transition-colors', isActive && 'text-primary')} />
                    <span className="flex-1 truncate">{label}</span>
                    {isActive && <span className="nav-rail-active-indicator" />}
                  </>
                )}
              </NavLink>
            ))}

            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5 mt-3">
              System
            </div>
            {NAV_SECONDARY.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass}>
                {({ isActive }) => (
                  <>
                    <Icon className={cn('w-4 h-4 shrink-0 transition-colors', isActive && 'text-primary')} />
                    <span className="flex-1 truncate">{label}</span>
                    {isActive && <span className="nav-rail-active-indicator" />}
                  </>
                )}
              </NavLink>
            ))}

            <div className="my-2 border-t border-sidebar-border/50" />
            <NavLink to="/" className={linkClass}>
              <ArrowLeft className="w-4 h-4 shrink-0" />
              <span className="flex-1 truncate">Back to Wiki</span>
            </NavLink>
          </nav>

          {/* Activity */}
          {totalActivity > 0 && (
            <div className="mx-2 mt-2 p-3 rounded-lg glass-strong space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em]">
                <Activity className="w-3 h-3" />
                <span>Activity</span>
              </div>
              {badges.confirmations > 0 && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Confirmations</span>
                  <Badge variant="destructive">{badges.confirmations}</Badge>
                </div>
              )}
              {badges.proposals > 0 && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Proposals</span>
                  <Badge variant="outline">{badges.proposals}</Badge>
                </div>
              )}
              {badges.notifications > 0 && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Notifications</span>
                  <Badge>{badges.notifications}</Badge>
                </div>
              )}
            </div>
          )}

          <div className="flex-1" />

          {/* User / status footer */}
          <div className="m-2 p-2.5 rounded-lg glass-strong">
            <div className="flex items-center gap-2.5">
              <div className="shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-primary/30 to-accent/30 border border-primary/20 flex items-center justify-center">
                <Bot className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-foreground truncate">
                  {currentWiki?.name || 'No wiki'}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="status-dot status-dot--live bg-success" />
                  <span className="text-[10px] text-muted-foreground">Connected</span>
                </div>
              </div>
            </div>
          </div>
        </aside>
      )}

      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          className="absolute top-4 left-4 z-20 p-2 glass-strong rounded-lg hover:bg-white/[0.06] transition-colors"
          aria-label="Expand sidebar"
        >
          <PanelLeftOpen className="w-4 h-4 text-foreground" />
        </button>
      )}

      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        <Backdrop />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
