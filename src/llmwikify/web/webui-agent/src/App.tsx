import { useState, useEffect } from 'react';
import { AgentChat } from './components/AgentChat';
import { Confirmations } from './components/Confirmations';
import { DreamLog } from './components/DreamLog';
import { DreamProposals } from './components/DreamProposals';
import { EditHistory } from './components/EditHistory';
import { IngestLog } from './components/IngestLog';
import { LLMSettings } from './components/LLMSettings';
import { PPTGenerator } from './components/PPTGenerator';
import { ResearchPanel } from './components/ResearchPanel';
import { TaskMonitor } from './components/TaskMonitor';
import { WikiSelector } from './components/WikiSelector';
import { useAgentWikiStore } from './stores/agentWikiStore';
import { api } from './api';
import { Card } from './components/ui/Card';
import { Badge } from './components/ui/Badge';

type ViewMode = 'chat' | 'research' | 'ppt' | 'tasks' | 'confirmations' | 'proposals' | 'dream' | 'ingest' | 'history' | 'settings';

interface BadgeCounts {
  confirmations: number;
  proposals: number;
  notifications: number;
}

function LazyWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-hidden">
      {children}
    </div>
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
    <div className="flex h-screen bg-[var(--bg-primary)] text-[var(--text-primary)]">
      <aside className="w-64 bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col">
        <div className="p-4 border-b border-[var(--border)]">
          <h1 className="text-lg font-bold text-[var(--accent)]">llmwikify Agent</h1>
        </div>

        <WikiSelector />

        <nav className="p-2 space-y-1">
          <NavButton active={view === 'chat'} onClick={() => setView('chat')}>
            Agent Chat
          </NavButton>
          <NavButton active={view === 'research'} onClick={() => setView('research')}>
            Quick Research
          </NavButton>
          <NavButton active={view === 'ppt'} onClick={() => setView('ppt')}>
            PPT Generator
          </NavButton>
          <NavButton active={view === 'tasks'} onClick={() => setView('tasks')}>
            Tasks
          </NavButton>
          <div className="border-t border-[var(--border)] my-2" />
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
          <NavButton active={view === 'settings'} onClick={() => setView('settings')}>
            LLM Settings
          </NavButton>
        </nav>

        <div className="mt-auto p-4 border-t border-[var(--border)] text-xs text-[var(--text-secondary)]">
          <a href="/" className="hover:text-[var(--accent)]">← Wiki UI</a>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden">
          {view === 'chat' && <AgentChat />}
          {view === 'research' && <ResearchPanel />}
          {view === 'ppt' && <PPTGenerator />}
          {view === 'tasks' && <LazyWrapper><TaskMonitor /></LazyWrapper>}
          {view === 'confirmations' && <LazyWrapper><Confirmations /></LazyWrapper>}
          {view === 'proposals' && <LazyWrapper><DreamProposals /></LazyWrapper>}
          {view === 'dream' && <LazyWrapper><DreamLog /></LazyWrapper>}
          {view === 'ingest' && <LazyWrapper><IngestLog /></LazyWrapper>}
          {view === 'history' && <LazyWrapper><EditHistory /></LazyWrapper>}
          {view === 'settings' && <LazyWrapper><LLMSettings /></LazyWrapper>}
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
          ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
      }`}
    >
      {active && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-[var(--accent)] rounded-r" />}
      <div className="flex items-center justify-between">
        <span>{children}</span>
        {badge !== undefined && badge > 0 && (
          <Badge variant="error">{badge > 99 ? '99+' : badge}</Badge>
        )}
      </div>
    </button>
  );
}

export default App;