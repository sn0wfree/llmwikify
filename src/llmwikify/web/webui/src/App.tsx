import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { FileTree } from './components/FileTree';
import { Editor } from './components/Editor';
import { SearchBar } from './components/SearchBar';
import { HealthStatus } from './components/HealthStatus';
import { Insights } from './components/Insights';
import { Notifications } from './components/Notifications';
import { ToastProvider } from './components/Toast';
import { api, WikiStatus, SinkStatus } from './api';

const KnowledgeGrowth = lazy(() => import('./components/KnowledgeGrowth').then(m => ({ default: m.KnowledgeGrowth })));
const AgentChat = lazy(() => import('./components/AgentChat').then(m => ({ default: m.AgentChat })));
const TaskMonitor = lazy(() => import('./components/TaskMonitor').then(m => ({ default: m.TaskMonitor })));
const DreamLog = lazy(() => import('./components/DreamLog').then(m => ({ default: m.DreamLog })));
const Confirmations = lazy(() => import('./components/Confirmations').then(m => ({ default: m.Confirmations })));
const DreamProposals = lazy(() => import('./components/DreamProposals').then(m => ({ default: m.DreamProposals })));
const IngestLog = lazy(() => import('./components/IngestLog').then(m => ({ default: m.IngestLog })));
const EditHistory = lazy(() => import('./components/EditHistory').then(m => ({ default: m.EditHistory })));

type ViewMode = 'edit' | 'dashboard' | 'insights' | 'chat' | 'tasks' | 'dream' | 'confirmations' | 'proposals' | 'ingest' | 'history';

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
  const [agentEnabled, setAgentEnabled] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.wiki.status();
      setStatus(s);
      const sk = await api.wiki.sinkStatus();
      setSinkStatus(sk);
    } catch {
      // API not available
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 30000);
    return () => clearInterval(interval);
  }, [loadStatus]);

  return (
    <ToastProvider>
    <div className="flex h-screen bg-slate-900 text-slate-100">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? 'w-64' : 'w-0'
        } transition-all duration-200 bg-slate-800 border-r border-slate-700 flex flex-col overflow-hidden`}
      >
        <div className="p-4 border-b border-slate-700">
          <h1 className="text-lg font-bold text-blue-400">llmwikify</h1>
          {status && (
            <p className="text-xs text-slate-400 mt-1">
              {status.page_count} pages
            </p>
          )}
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
          {agentEnabled && (
            <>
              <div className="border-t border-slate-700 my-2" />
              <NavButton active={view === 'chat'} onClick={() => setView('chat')}>
                Agent Chat
              </NavButton>
              <NavButton active={view === 'tasks'} onClick={() => setView('tasks')}>
                Tasks
              </NavButton>
              <div className="border-t border-slate-700 my-2" />
              <NavButton active={view === 'confirmations'} onClick={() => setView('confirmations')}>
                Confirmations
              </NavButton>
              <NavButton active={view === 'proposals'} onClick={() => setView('proposals')}>
                Dream Proposals
              </NavButton>
              <NavButton active={view === 'dream'} onClick={() => setView('dream')}>
                Dream Log
              </NavButton>
              <NavButton active={view === 'ingest'} onClick={() => setView('ingest')}>
                Ingest Log
              </NavButton>
              <NavButton active={view === 'history'} onClick={() => setView('history')}>
                Edit History
              </NavButton>
            </>
          )}
        </nav>

        <div className="mt-auto p-2 border-t border-slate-700">
          <HealthStatus status={status} sinkStatus={sinkStatus} />
          <div className="mt-2 px-2">
            <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
              <input
                type="checkbox"
                checked={agentEnabled}
                onChange={(e) => setAgentEnabled(e.target.checked)}
                className="rounded border-slate-600 bg-slate-700"
              />
              Enable Agent
            </label>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-12 bg-slate-800 border-b border-slate-700 flex items-center px-4 gap-2">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-400"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <SearchBar
            onResult={(page) => {
              setSelectedPage(page);
              setView('edit');
            }}
          />
          <Notifications />
        </header>

        {/* View Content */}
        <div className="flex-1 overflow-hidden">
          {view === 'edit' && (
            <Editor
              selectedPage={selectedPage}
              onPageSelect={setSelectedPage}
            />
          )}
          {view === 'dashboard' && <LazyWrapper><KnowledgeGrowth /></LazyWrapper>}
          {view === 'insights' && <Insights />}
          {view === 'chat' && agentEnabled && <LazyWrapper><AgentChat /></LazyWrapper>}
          {view === 'tasks' && agentEnabled && <LazyWrapper><TaskMonitor /></LazyWrapper>}
          {view === 'confirmations' && agentEnabled && <LazyWrapper><Confirmations /></LazyWrapper>}
          {view === 'proposals' && agentEnabled && <LazyWrapper><DreamProposals /></LazyWrapper>}
          {view === 'dream' && agentEnabled && <LazyWrapper><DreamLog /></LazyWrapper>}
          {view === 'ingest' && agentEnabled && <LazyWrapper><IngestLog /></LazyWrapper>}
          {view === 'history' && agentEnabled && <LazyWrapper><EditHistory /></LazyWrapper>}
        </div>
      </main>
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
