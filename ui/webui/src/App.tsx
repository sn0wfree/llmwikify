import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { Editor } from './components/wiki/Editor';
import { Insights } from './components/wiki/Insights';
import { Notifications } from './components/wiki/Notifications';
import { HealthStatus } from './components/wiki/HealthStatus';
import { WikiSelector } from './components/wiki/WikiSelector';
import { CrossWikiSearch } from './components/wiki/CrossWikiSearch';
import { WikiManager } from './components/wiki/WikiManager';
import { TaskMonitor } from './components/wiki/TaskMonitor';
import { Confirmations } from './components/wiki/Confirmations';
import { DreamProposals } from './components/wiki/DreamProposals';
import { DreamLog } from './components/wiki/DreamLog';
import { IngestLog } from './components/wiki/IngestLog';
import { EditHistory } from './components/wiki/EditHistory';
import { AgentChat } from './components/agent/AgentChat';
import { ResearchPanel } from './components/agent/ResearchPanel';
import { AutoResearchPanel } from './components/agent/AutoResearchPanel';
import { LLMSettings } from './components/agent/LLMSettings';
import { Backdrop } from './components/agent/Backdrop';
import { Badge } from './components/ui/Badge';
import { useWikiStore } from './stores/wikiStore';
import { api } from './api';

const KnowledgeGrowth = lazy(() =>
  import('./components/wiki/KnowledgeGrowth').then(m => ({ default: m.KnowledgeGrowth }))
);

type ViewMode =
  | 'edit' | 'dashboard' | 'insights'
  | 'chat' | 'research' | 'autoresearch'
  | 'tasks' | 'settings';

interface BadgeCounts {
  confirmations: number;
  proposals: number;
  notifications: number;
}

function App() {
  const [view, setView] = useState<ViewMode>('edit');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showManager, setShowManager] = useState(false);
  const [badges, setBadges] = useState<BadgeCounts>({ confirmations: 0, proposals: 0, notifications: 0 });
  const { wikis, currentWikiId, loadWikis } = useWikiStore();

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
      } catch {
        /* silent */
      }
    };
    fetchBadges();
    const interval = setInterval(fetchBadges, 30000);
    return () => clearInterval(interval);
  }, [currentWikiId]);

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
            <NavButton active={view === 'edit'} onClick={() => setView('edit')}>
              Editor
            </NavButton>
            <NavButton active={view === 'dashboard'} onClick={() => setView('dashboard')}>
              Dashboard
            </NavButton>
            <NavButton active={view === 'insights'} onClick={() => setView('insights')}>
              Insights
            </NavButton>

            <div className="text-xs text-[var(--text-secondary)] px-3 py-1 mt-3">Agent</div>
            <NavButton active={view === 'chat'} onClick={() => setView('chat')}>
              Agent Chat
            </NavButton>
            <NavButton active={view === 'research'} onClick={() => setView('research')}>
              Research
            </NavButton>
            <NavButton active={view === 'autoresearch'} onClick={() => setView('autoresearch')}>
              AutoResearch
            </NavButton>

            <div className="text-xs text-[var(--text-secondary)] px-3 py-1 mt-3">System</div>
            <NavButton active={view === 'tasks'} onClick={() => setView('tasks')}>
              Tasks
            </NavButton>
            <NavButton active={view === 'settings'} onClick={() => setView('settings')}>
              LLM Settings
            </NavButton>

            <div className="border-t border-[var(--border)] my-2" />
            <div className="text-xs text-[var(--text-secondary)] px-3 py-1">Activity</div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Confirmations: <Badge variant="error">{badges.confirmations}</Badge>
            </div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Proposals: <Badge variant="warning">{badges.proposals}</Badge>
            </div>
            <div className="px-3 py-1 text-sm text-[var(--text-secondary)]">
              Notifications: <Badge>{badges.notifications}</Badge>
            </div>
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
        <Backdrop />
        <div className="p-3 border-b border-[var(--border)] flex items-center gap-3">
          <CrossWikiSearch />
          <Notifications />
        </div>
        <div className="flex-1 flex flex-col overflow-hidden">
          <Suspense fallback={<div className="p-6 text-[var(--text-secondary)]">Loading...</div>}>
            {view === 'edit' && <Editor />}
            {view === 'dashboard' && <KnowledgeGrowth />}
            {view === 'insights' && <Insights />}
            {view === 'chat' && <AgentChat />}
            {view === 'research' && <ResearchPanel />}
            {view === 'autoresearch' && <AutoResearchPanel />}
            {view === 'tasks' && <TaskMonitor />}
            {view === 'settings' && <LLMSettings />}
          </Suspense>
        </div>
      </main>

      {showManager && <WikiManager onClose={() => setShowManager(false)} />}
    </div>
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
      className={`w-full text-left px-3 py-2 rounded text-sm transition-colors relative ${
        active
          ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
      }`}
    >
      {active && <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-[var(--accent)] rounded-r" />}
      <span>{children}</span>
    </button>
  );
}

export default App;
