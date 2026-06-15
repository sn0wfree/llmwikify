/**
 * ReproductionPanel — 5-Phase Paper Reproduction Panel (v0.4.0)
 *
 * Layout matches AutoResearchPanel:
 *   - Sidebar (sessions list)
 *   - Main detail area with 3 tabs:
 *       概览 (Overview): 5-step progress + event log
 *       指标 (Metrics): MetricCards + start config
 *       Wiki:   ArtifactList (links to generated pages)
 *
 * Differences from AutoResearchPanel:
 *   - Pipeline is synchronous (5 phases complete in one POST /start),
 *     so we use polling-based refresh instead of SSE streaming.
 *   - 5 phases (extract / data / backtest / analyze / finalize) instead of 6.
 *   - Right pane emphasizes quantitative metrics (Sharpe / MDD / etc.)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, X, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  STATUS_LABELS,
  deleteReproductionSession,
  eventToPhase,
  getReproduction,
  listReproductionArtifacts,
  listReproductionSessions,
  parseParams,
  type ReproductionArtifact,
  type ReproductionEvent,
  type ReproductionSession,
  type StartReproductionResponse,
} from '../../lib/reproduction-api';
import { FiveStepBar } from './FiveStepBar';
import { MetricCards } from './MetricCards';
import { EventLog } from './EventLog';
import { ArtifactList } from './ArtifactList';
import { NewSessionForm } from './NewSessionForm';

// ─── Helpers ──────────────────────────────────────────────────

function formatRelativeTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

function truncate(s: string, n: number): string {
  if (!s) return '';
  return s.length <= n ? s : s.slice(0, n) + '…';
}

// ─── SessionSidebar (left) ───────────────────────────────────

interface SessionSidebarProps {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

function SessionSidebar({ selectedId, onSelect }: SessionSidebarProps) {
  const [sessions, setSessions] = useState<ReproductionSession[]>([]);
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listReproductionSessions();
      setSessions(data.sessions || []);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  // Refresh list when a session completes
  useEffect(() => {
    if (!selectedId) return;
    const interval = setInterval(loadSessions, 5000);
    return () => clearInterval(interval);
  }, [selectedId, loadSessions]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await deleteReproductionSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (selectedId === sessionId) onSelect(null);
    } catch { /* ignore */ }
  };

  return (
    <div className="flex flex-col h-full min-h-0 border-r border-border">
      <div className="p-3 border-b border-border">
        <button
          onClick={() => onSelect(null)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium
            bg-primary text-white hover:bg-primary/90 transition-colors"
        >
          <span>＋</span>
          <span>新建复现</span>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && sessions.length === 0 ? (
          <div className="p-3 text-xs text-muted-foreground text-center">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="p-3 text-xs text-muted-foreground text-center">
            <div className="mb-1">暂无历史会话</div>
            <div className="text-[10px] opacity-70">点上方"新建"开始 5 阶段复现</div>
          </div>
        ) : (
          sessions.map((s) => {
            const status = STATUS_LABELS[s.status] || STATUS_LABELS.error;
            return (
              <div key={s.id} className="relative group">
                <button
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    'w-full text-left px-3 py-2.5 border-b border-border transition-colors',
                    selectedId === s.id
                      ? 'bg-primary/10'
                      : 'hover:bg-muted/50'
                  )}
                >
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={cn('text-[11px]', status.color)}>{status.icon}</span>
                    <span className="text-xs font-medium truncate">{s.paper_id}</span>
                  </div>
                  <div className="text-[10px] text-muted-foreground font-mono truncate">
                    {s.symbol} · {s.start_date}→{s.end_date}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {formatRelativeTime(s.created_at)}
                  </div>
                </button>
                <button
                  onClick={(e) => handleDelete(e, s.id)}
                  className={cn(
                    'absolute right-1.5 top-1/2 -translate-y-1/2',
                    'opacity-0 group-hover:opacity-100 transition-opacity',
                    'text-muted-foreground hover:text-destructive p-1 rounded hover:bg-white/[0.06]',
                  )}
                  title="删除会话"
                  aria-label="删除会话"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─── Session header ──────────────────────────────────────────

function SessionHeader({
  session,
  metrics,
  signalType,
  source,
  onRefresh,
}: {
  session: ReproductionSession;
  metrics: StartReproductionResponse['metrics'] | null;
  signalType?: string;
  source?: string;
  onRefresh: () => void;
}) {
  const status = STATUS_LABELS[session.status] || STATUS_LABELS.error;
  const params = parseParams(session.strategy_params_json);

  return (
    <div className="p-4 border-b border-border bg-card">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={cn('text-sm font-bold', status.color)}>
              {status.icon} {status.text}
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              {session.id.slice(0, 12)}
            </span>
          </div>
          <div className="text-sm text-foreground font-medium truncate">
            {session.paper_id} · <span className="font-mono">{session.symbol}</span>
          </div>
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {session.start_date} → {session.end_date}
            {source && <span className="ml-2">· 数据源 <span className="font-mono">{source}</span></span>}
          </div>
        </div>
        <button
          onClick={onRefresh}
          className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded
            border border-border"
          title="刷新"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="mb-2">
        <FiveStepBar
          currentPhase={session.status === 'done' ? null :
            session.status === 'error' ? null : session.status}
          status={session.status}
        />
      </div>

      {signalType && (
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-muted-foreground">策略:</span>
          <span className="px-2 py-0.5 bg-primary/10 text-primary rounded font-mono">
            {signalType}
          </span>
          <span className="text-muted-foreground font-mono truncate">
            {JSON.stringify(params)}
          </span>
        </div>
      )}

      {session.status === 'done' && metrics && (
        <div className="mt-2 text-[11px] text-green-400">
          ✓ 完成 · Sharpe {metrics.sharpe_ratio.toFixed(3)} · {metrics.trades} 笔交易
        </div>
      )}
    </div>
  );
}

// ─── Main Panel ──────────────────────────────────────────────

type TabKey = 'overview' | 'metrics' | 'wiki';

const TABS: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'overview', label: '概览', icon: '◐' },
  { key: 'metrics',  label: '指标', icon: '◈' },
  { key: 'wiki',     label: 'Wiki', icon: '▤' },
];

export function ReproductionPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<ReproductionSession | null>(null);
  const [events, setEvents] = useState<ReproductionEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ReproductionArtifact[]>([]);
  const [metrics, setMetrics] = useState<StartReproductionResponse['metrics'] | null>(null);
  const [signalType, setSignalType] = useState<string | undefined>();
  const [source, setSource] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const pollingRef = useRef<number | null>(null);

  // Load session details
  const loadSession = useCallback(async (id: string) => {
    try {
      const data = await getReproduction(id);
      setSession(data.session);
      setEvents(data.events || []);

      // Try to extract metrics/signal from latest events
      const eventsList = data.events || [];
      for (let i = eventsList.length - 1; i >= 0; i--) {
        const payload = (() => {
          try { return JSON.parse(eventsList[i].payload_json); } catch { return {}; }
        })();
        if (eventsList[i].event_type === 'backtest.done' && payload) {
          setMetrics({
            sharpe_ratio: payload.sharpe ?? 0,
            max_drawdown: payload.mdd ?? 0,
            win_rate: payload.win_rate ?? 0,
            total_return: payload.total_return ?? 0,
            final_cash: payload.final_cash ?? 0,
            trades: payload.trades ?? 0,
          });
        }
        if (eventsList[i].event_type === 'extract.done' && payload.signal_type) {
          setSignalType(payload.signal_type);
        }
        if (eventsList[i].event_type === 'data.fetched' && payload.source) {
          setSource(payload.source);
        }
      }
    } catch {
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load artifacts
  const loadArtifacts = useCallback(async (id: string) => {
    try {
      const data = await listReproductionArtifacts(id);
      setArtifacts(data.artifacts || []);
    } catch {
      setArtifacts([]);
    }
  }, []);

  // On selection change
  useEffect(() => {
    if (!selectedId) {
      setSession(null);
      setEvents([]);
      setArtifacts([]);
      setMetrics(null);
      setSignalType(undefined);
      setSource(undefined);
      return;
    }
    setLoading(true);
    loadSession(selectedId);
    loadArtifacts(selectedId);
  }, [selectedId, loadSession, loadArtifacts]);

  // Polling for terminal sessions (in case SSE is added later)
  useEffect(() => {
    if (!selectedId || !session) return;
    if (session.status === 'done' || session.status === 'error') {
      // Stop polling, refresh once for final state
      loadArtifacts(selectedId);
      return;
    }
    // The pipeline is synchronous in v0.4.0, so polling is mostly a safety net
    pollingRef.current = window.setInterval(() => {
      loadSession(selectedId);
    }, 3000);
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [selectedId, session?.status, loadSession, loadArtifacts]);

  const handleNew = (id: string) => {
    setSelectedId(id);
    setActiveTab('overview');
  };

  const handleRefresh = () => {
    if (selectedId) {
      loadSession(selectedId);
      loadArtifacts(selectedId);
    }
  };

  const handleOpenWikiPage = (page: string) => {
    // Navigate to wiki editor at the given page
    // The page slug needs to be URL-encoded for routing
    window.open(`/#/edit?page=${encodeURIComponent(page)}`, '_blank');
  };

  if (!selectedId) {
    return (
      <div className="flex h-full min-h-0">
        <div className="w-72 shrink-0">
          <SessionSidebar selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <NewSessionForm onCreated={handleNew} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="w-72 shrink-0">
        <SessionSidebar selectedId={selectedId} onSelect={setSelectedId} />
      </div>

      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {loading && !session ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            加载中...
          </div>
        ) : session ? (
          <>
            <SessionHeader
              session={session}
              metrics={metrics}
              signalType={signalType}
              source={source}
              onRefresh={handleRefresh}
            />

            <div className="px-4 border-b border-border flex gap-1">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={cn(
                    'px-3 py-2 text-xs font-medium transition-colors relative',
                    activeTab === tab.key
                      ? 'text-primary'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {tab.icon} {tab.label}
                  {activeTab === tab.key && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
                  )}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto min-h-0 p-4">
              {activeTab === 'overview' && (
                <EventLog events={events} />
              )}
              {activeTab === 'metrics' && (
                <div className="space-y-4">
                  <div className="text-xs text-muted-foreground">
                    回测指标 (基于 {session.symbol} · {session.start_date} → {session.end_date})
                  </div>
                  <MetricCards metrics={metrics} />
                </div>
              )}
              {activeTab === 'wiki' && (
                <div className="space-y-3">
                  <div className="text-xs text-muted-foreground">
                    生成的 Wiki 页面 ({artifacts.length})
                  </div>
                  <ArtifactList artifacts={artifacts} onOpenPage={handleOpenWikiPage} />
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-red-400">
            加载失败
          </div>
        )}
      </div>
    </div>
  );
}