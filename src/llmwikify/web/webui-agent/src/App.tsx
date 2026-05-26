import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { AgentChat } from './components/AgentChat';
import { Confirmations } from './components/Confirmations';
import { DreamLog } from './components/DreamLog';
import { DreamProposals } from './components/DreamProposals';
import { EditHistory } from './components/EditHistory';
import { IngestLog } from './components/IngestLog';
import { TaskMonitor } from './components/TaskMonitor';
import { WikiSelector } from './components/WikiSelector';
import { useAgentWikiStore } from './stores/agentWikiStore';
import { api } from './api';

type ViewMode = 'chat' | 'tasks' | 'confirmations' | 'proposals' | 'dream' | 'ingest' | 'history';

interface BadgeCounts {
  confirmations: number;
  proposals: number;
  notifications: number;
}

function LazyWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-500">Loading...</div>}>
      {children}
    </Suspense>
  );
}

function App() {
  const [view, setView] = useState<ViewMode>('chat');
  const [badges, setBadges] = useState<BadgeCounts>({ confirmations: 0, proposals: 0, notifications: 0 });
  const { loadWikis, currentWikiId } = useAgentWikiStore();

  useEffect(() => {
    loadWikis();
  }, [loadWikis]);

  useEffect(() => {
    const fetchBadges = async () => {
      try {
        const status = await api.agent.status(currentWikiId || undefined);
        const proposalsCount = Object.values(status.dream_proposals || {}).reduce((a: number, b) => a + (Number(b) || 0), 0) as number;
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

  return (
    <div className="flex h-screen bg-slate-900 text-slate-100">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-800 border-r border-slate-700 flex flex-col">
        <div className="p-4 border-b border-slate-700">
          <h1 className="text-lg font-bold text-blue-400">llmwikify Agent</h1>
        </div>

        <WikiSelector />

        <nav className="p-2 space-y-1">
          <NavButton active={view === 'chat'} onClick={() => setView('chat')}>
            Agent Chat
          </NavButton>
          <NavButton active={view === 'tasks'} onClick={() => setView('tasks')}>
            Tasks
          </NavButton>
          <div className="border-t border-slate-700 my-2" />
          <NavButton active={view === 'confirmations'} onClick={() => setView('confirmations')} badge={badges.confirmations}>
            Confirmations
          </NavButton>
          <NavButton active={view === 'proposals'} onClick={() => setView('proposals')} badge={badges.proposals}>
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
        </nav>

        <div className="mt-auto p-4 border-t border-slate-700 text-xs text-slate-500">
          <a href="/" className="hover:text-blue-400">← Wiki UI</a>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden">
          {view === 'chat' && <AgentChat />}
          {view === 'tasks' && <LazyWrapper><TaskMonitor /></LazyWrapper>}
          {view === 'confirmations' && <LazyWrapper><Confirmations /></LazyWrapper>}
          {view === 'proposals' && <LazyWrapper><DreamProposals /></LazyWrapper>}
          {view === 'dream' && <LazyWrapper><DreamLog /></LazyWrapper>}
          {view === 'ingest' && <LazyWrapper><IngestLog /></LazyWrapper>}
          {view === 'history' && <LazyWrapper><EditHistory /></LazyWrapper>}
        </div>
      </main>
    </div>
  );
}

function NavButton({
  active,
  onClick,
  children,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  badge?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 rounded text-sm transition-colors relative ${
        active
          ? 'bg-blue-600/20 text-blue-400'
          : 'text-slate-300 hover:bg-slate-700'
      }`}
    >
      {active && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-blue-400 rounded-r" />}
      <div className="flex items-center justify-between">
        <span>{children}</span>
        {badge !== undefined && badge > 0 && (
          <span className="px-1.5 py-0.5 text-xs bg-red-500 text-white rounded-full min-w-[20px] text-center">
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </div>
    </button>
  );
}

export default App;