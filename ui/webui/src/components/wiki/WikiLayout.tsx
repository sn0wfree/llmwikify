import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  FileText, BarChart3, Lightbulb, Bot, PanelLeftClose, PanelLeftOpen,
  BookOpen, Search, Bell, Sun, Moon, Sparkles, X,
} from 'lucide-react';
import { Notifications } from './Notifications';
import { HealthStatus } from './HealthStatus';
import { WikiSelector } from './WikiSelector';
import { CrossWikiSearch } from './CrossWikiSearch';
import { WikiManager } from './WikiManager';
import { useWikiStore } from '../../stores/wikiStore';
import { cn } from '@/lib/utils';

const NAV_PRIMARY = [
  { to: '/edit', label: 'Editor', icon: FileText },
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/insights', label: 'Insights', icon: Lightbulb },
] as const;

interface SearchPaletteProps {
  open: boolean;
  onClose: () => void;
  query: string;
  onQueryChange: (q: string) => void;
}

function SearchPalette({ open, onClose, query, onQueryChange }: SearchPaletteProps) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm flex items-start justify-center pt-[20vh] animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl glass-strong rounded-xl shadow-elevated overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/50">
          <Search className="w-4 h-4 text-muted-foreground" />
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search wiki pages..."
            className="flex-1 bg-transparent border-0 outline-none text-sm text-foreground placeholder:text-muted-foreground"
          />
          <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-muted-foreground">Esc</kbd>
          <button
            onClick={onClose}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-white/[0.06] transition-colors"
            aria-label="Close search"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="px-4 py-8 text-center text-xs text-muted-foreground">
          {query ? 'Press Enter to search' : 'Type to search across all pages...'}
        </div>
      </div>
    </div>
  );
}

export function WikiLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showManager, setShowManager] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (document.documentElement.getAttribute('data-theme') as 'dark' | 'light') || 'dark',
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const { loadWikis, currentWikiId, wikis } = useWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  // ⌘K / Ctrl+K to open search palette
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Theme toggle
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
                  <BookOpen className="w-4 h-4 text-primary-foreground" strokeWidth={2.5} />
                </div>
                <div className="absolute -inset-0.5 rounded-lg bg-gradient-to-br from-primary/40 to-accent/0 blur-md -z-10 opacity-60" />
              </div>
              <div className="min-w-0">
                <h1 className="text-sm font-semibold text-sidebar-foreground leading-none tracking-tight">
                  llmwikify
                </h1>
                <p className="text-[10px] text-muted-foreground mt-0.5 leading-none">
                  Wiki workspace
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

          {/* Primary nav */}
          <nav className="px-2 pt-2 space-y-0.5">
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.12em] px-3 py-1.5">
              Workspace
            </div>
            {NAV_PRIMARY.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass} end={to === '/edit'}>
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
            <NavLink to="/agent" className={linkClass}>
              <Bot className="w-4 h-4 shrink-0" />
              <span className="flex-1 truncate">Agent</span>
            </NavLink>
          </nav>

          <div className="flex-1" />

          <HealthStatus currentWiki={currentWiki} />

          {/* Theme toggle */}
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
        {/* Top bar */}
        <div className="px-4 py-2.5 border-b border-border/50 flex items-center justify-between gap-3 glass">
          <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
            <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
            <span className="truncate">
              {currentWiki?.name ? `${currentWiki.name}` : 'No wiki selected'}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => setSearchOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground glass hover:bg-white/[0.04] transition-colors"
              aria-label="Open search"
            >
              <Search className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Search…</span>
              <kbd className="px-1 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono hidden md:inline">⌘K</kbd>
            </button>
            <Notifications />
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </div>
      </main>

      {showManager && <WikiManager onClose={() => setShowManager(false)} />}

      <SearchPalette
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        query={searchQuery}
        onQueryChange={setSearchQuery}
      />
    </div>
  );
}
