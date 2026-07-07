import { useState, useEffect, useCallback } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  BookOpen, Sparkles, FileText, BarChart3, Lightbulb,
  MessageSquare, Search, CheckSquare, Settings,
  PanelLeftClose, PanelLeftOpen, Bot, Moon, Sun,
  Database, AlertTriangle,
} from 'lucide-react';
import { Backdrop } from './Backdrop';
import { Notifications } from '../wiki/Notifications';
import { HealthStatus } from '../wiki/HealthStatus';
import { WikiSelector } from '../wiki/WikiSelector';
import { WikiManager } from '../wiki/WikiManager';
import { Badge } from '../ui/badge';
import { UnifiedSearch } from './UnifiedSearch';
import { api } from '../../api';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

const NAV_WIKI = [
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/edit', label: 'Editor', icon: FileText },
] as const;

const NAV_AGENT = [
  { to: '/agent/chat', label: 'Chat', icon: MessageSquare },
  { to: '/agent/autoresearch', label: 'Research', icon: Search },
  { to: '/agent/confirmations', label: 'Confirmations', icon: AlertTriangle },
  { to: '/agent/tasks', label: 'Tasks', icon: CheckSquare },
  { to: '/agent/settings', label: 'Settings', icon: Settings },
] as const;

const NAV_INSIGHTS = [
  { to: '/insights', label: 'Insights', icon: Lightbulb },
  { to: '/insights/dream', label: 'Dream', icon: Sparkles },
  { to: '/insights/sink', label: 'Sink', icon: Database },
] as const;

interface BadgeCounts {
  confirmations: number;
  proposals: number;
}

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showManager, setShowManager] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (document.documentElement.getAttribute('data-theme') as 'dark' | 'light') || 'dark',
  );
  const [badges, setBadges] = useState<BadgeCounts>({ confirmations: 0, proposals: 0 });
  const [searchOpen, setSearchOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const isAgent = location.pathname.startsWith('/agent');
  const { loadWikis, currentWikiId, wikis } = useWikiStore();

  const handleSearchOpen = useCallback(() => setSearchOpen(true), []);
  const handleSearchClose = useCallback(() => setSearchOpen(false), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  useEffect(() => {
    const fetchBadges = async () => {
      try {
        const status = await api.agent.status(currentWikiId || undefined);
        const proposalsCount = Object.values(status.wiki_dream_proposals || {})
          .reduce((a: number, b) => a + (Number(b) || 0), 0);
        setBadges({
          confirmations: status.pending_confirmations || 0,
          proposals: proposalsCount,
        });
      } catch { /* silent */ }
    };
    fetchBadges();
    const interval = setInterval(fetchBadges, 30000);
    return () => clearInterval(interval);
  }, [currentWikiId]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'group relative flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm transition-all duration-200',
      isActive
        ? 'bg-primary/12 text-foreground font-medium'
        : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
    );

  const currentWiki = wikis.find((w) => w.wiki_id === currentWikiId);

  return (
    <div className="flex h-screen bg-background text-foreground relative">
      {sidebarOpen && (
        <aside
          className="w-64 shrink-0 flex flex-col border-r border-sidebar-border glass"
          style={{ background: 'color-mix(in srgb, var(--sidebar) 75%, transparent)' }}
        >
          <div className="px-4 py-4 flex items-center justify-between border-b border-sidebar-border/50">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="relative shrink-0">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-accent flex items-center justify-center shadow-soft">
                  <BookOpen className="w-4 h-4 text-primary-foreground" strokeWidth={2.5} />
                </div>
                <div className="absolute -inset-0.5 rounded-lg bg-gradient-to-br from-primary/40 to-accent/0 blur-md -z-10 opacity-60" />
              </div>
              <div className="min-w-0">
                <h1 className="text-sm font-semibold text-sidebar-foreground leading-none tracking-tight">
                  llmwikify
                </h1>
                <p className="text-[10px] text-muted-foreground mt-0.5 leading-none">
                  Workspace
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

          <WikiSelector onOpenManager={() => setShowManager(true)} />

          <nav className="px-2 pt-2 space-y-0.5">
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5">
              Wiki
            </div>
            {NAV_WIKI.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass} end={to === '/dashboard'}>
                {({ isActive }) => (
                  <>
                    <Icon className={cn('w-4 h-4 shrink-0 transition-colors', isActive && 'text-primary')} />
                    <span className="flex-1 truncate">{label}</span>
                    {isActive && <span className="nav-rail-active-indicator" />}
                  </>
                )}
              </NavLink>
            ))}

            <div className="border-t border-sidebar-border/30 mx-2 my-1.5" />

            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5">
              Agent
            </div>
            {NAV_AGENT.map(({ to, label, icon: Icon }) => (
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

            <div className="border-t border-sidebar-border/30 mx-2 my-1.5" />

            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5">
              Insights
            </div>
            {NAV_INSIGHTS.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass} end={to === '/insights'}>
                {({ isActive }) => (
                  <>
                    <Icon className={cn('w-4 h-4 shrink-0 transition-colors', isActive && 'text-primary')} />
                    <span className="flex-1 truncate">{label}</span>
                    {isActive && <span className="nav-rail-active-indicator" />}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="flex-1" />

          <HealthStatus currentWiki={currentWiki} />

          <div className="m-2 mt-0 flex items-center gap-1 p-1 rounded-lg glass-strong">
            <button
              onClick={() => setTheme('dark')}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-xs transition-colors',
                theme === 'dark'
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              aria-label="Dark theme"
            >
              <Moon className="w-3.5 h-3.5" />
              <span>Dark</span>
            </button>
            <button
              onClick={() => setTheme('light')}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-xs transition-colors',
                theme === 'light'
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              aria-label="Light theme"
            >
              <Sun className="w-3.5 h-3.5" />
              <span>Light</span>
            </button>
          </div>

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
        <div className="px-4 py-2.5 border-b border-border/50 flex items-center justify-between gap-3 glass">
          <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
            <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
            <span className="truncate">
              {currentWiki?.name ? `${currentWiki.name}` : 'No wiki selected'}
            </span>
          </div>
          <button
            onClick={handleSearchOpen}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg glass hover:bg-white/[0.04] text-muted-foreground hover:text-foreground transition-colors text-xs"
            aria-label="Search (⌘K)"
          >
            <Search className="w-3.5 h-3.5" />
            <kbd className="hidden sm:inline px-1 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono">⌘K</kbd>
          </button>
          <div className="flex items-center gap-2 shrink-0">
            {badges.confirmations > 0 && (
              <Badge variant="destructive" title="Pending confirmations">
                {badges.confirmations}
              </Badge>
            )}
            {badges.proposals > 0 && (
              <Badge variant="outline" title="Wiki dream proposals">
                {badges.proposals}
              </Badge>
            )}
            <Notifications />
          </div>
        </div>

        {isAgent && <Backdrop />}

        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>

      {showManager && <WikiManager onClose={() => setShowManager(false)} />}
      <UnifiedSearch open={searchOpen} onClose={handleSearchClose} />
    </div>
  );
}