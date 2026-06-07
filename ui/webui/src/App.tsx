import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { FileTree } from './components/FileTree';
import { Editor } from './components/Editor';
import { HealthStatus } from './components/HealthStatus';
import { Insights } from './components/Insights';
import { Notifications } from './components/Notifications';
import { ToastProvider } from './components/Toast';
import { WikiSelector } from './components/WikiSelector';
import { CrossWikiSearch } from './components/CrossWikiSearch';
import { WikiManager } from './components/WikiManager';
import { useWikiStore } from './stores/wikiStore';
import { api, WikiStatus, SinkStatus } from './api';

const KnowledgeGrowth = lazy(() => import('./components/KnowledgeGrowth').then(m => ({ default: m.KnowledgeGrowth })));

type ViewMode = 'edit' | 'dashboard' | 'insights';

function LazyWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-500">Loading...</div>}>
      {children}
    </Suspense>
  );
}

function App() {
  const [status, setStatus] = useState<WikiStatus | null>(null);
  const [sinkStatus, setSinkStatus] = useState<SinkStatus | null>(null);
  const [view, setView] = useState<ViewMode>('edit');
  const [selectedPage, setSelectedPage] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showWikiManager, setShowWikiManager] = useState(false);

  const { loadWikis, currentWikiId, isMultiWikiMode, switchWiki, updateWikiPageCount } = useWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  const loadStatus = useCallback(async () => {
    try {
      let s: WikiStatus;
      if (isMultiWikiMode && currentWikiId) {
        s = await api.wiki.scoped.status(currentWikiId);
      } else {
        s = await api.wiki.status();
      }
      setStatus(s);
      if (currentWikiId) {
        updateWikiPageCount(currentWikiId, s.page_count);
      }
    } catch {
      // API not available
    }

    try {
      const sk = await api.wiki.sinkStatus();
      setSinkStatus(sk);
    } catch {
      setSinkStatus(null);
    }
  }, [currentWikiId, isMultiWikiMode]);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 30000);
    return () => clearInterval(interval);
  }, [loadStatus]);

  const handleSearchResult = useCallback((pageName: string, wikiId: string) => {
    if (wikiId !== currentWikiId) {
      switchWiki(wikiId);
    }
    setSelectedPage(pageName);
    setView('edit');
  }, [currentWikiId, switchWiki]);

  return (
    <ToastProvider>
    <div className="flex h-screen bg-slate-900 text-slate-100">
      <aside
        className={`${
          sidebarOpen ? 'w-64' : 'w-0'
        } transition-all duration-200 bg-slate-800 border-r border-slate-700 flex flex-col overflow-hidden`}
      >
        <div className="border-b border-slate-700">
          <div className="p-4">
            <div className="flex items-baseline gap-2">
              <h1 className="text-lg font-bold text-blue-400">llmwikify</h1>
              {status?.version && (
                <span className="text-xs text-slate-600">v{status.version}</span>
              )}
            </div>
          </div>
          <WikiSelector onOpenManager={() => setShowWikiManager(true)} />
        </div>

        <nav className="p-2 space-y-1">
          <NavButton active={view === 'edit'} onClick={() => setView('edit')}>
            Editor
          </NavButton>
          <NavButton active={view === 'dashboard'} onClick={() => setView('dashboard')}>
            Dashboard
          </NavButton>
          <NavButton active={view === 'insights'} onClick={() => setView('insights')}>
            Insights
          </NavButton>
        </nav>

        <div className="mt-auto p-4 border-t border-slate-700">
          <HealthStatus status={status} sinkStatus={sinkStatus} />
          <div className="mt-2 text-xs text-slate-500">
            <a href="/agent" className="hover:text-blue-400">→ Agent UI</a>
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-12 bg-slate-800 border-b border-slate-700 flex items-center px-4 gap-2">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-400"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <CrossWikiSearch onResult={handleSearchResult} />
          <Notifications />
        </header>

        <div className="flex-1 overflow-hidden">
          {view === 'edit' && (
            <Editor
              selectedPage={selectedPage}
              onPageSelect={setSelectedPage}
              currentWikiId={currentWikiId}
            />
          )}
          {view === 'dashboard' && <LazyWrapper><KnowledgeGrowth currentWikiId={currentWikiId} isMultiWikiMode={isMultiWikiMode} /></LazyWrapper>}
          {view === 'insights' && <Insights />}
        </div>
      </main>

      {showWikiManager && (
        <WikiManager onClose={() => setShowWikiManager(false)} />
      )}
    </div>
    </ToastProvider>
  );
}

function NavButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
        active
          ? 'bg-blue-600/20 text-blue-400'
          : 'text-slate-300 hover:bg-slate-700'
      }`}
    >
      {children}
    </button>
  );
}

export default App;