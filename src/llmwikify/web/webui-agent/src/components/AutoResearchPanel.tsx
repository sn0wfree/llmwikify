/**
 * AutoResearchPanel — 6-Step Framework Research Panel (v5)
 *
 * Sidebar (sessions) + main detail area with 4 tabs:
 *   - Overview: events log + meta
 *   - Sources:  list with evidence_score bars
 *   - 6 步:     6 step result panels (clarify / evidence / reasoning /
 *               structure / report / compliance)
 *   - Report:   reuses ReportDetail for markdown rendering
 *
 * Pattern follows PPTSidebar (refreshKey + 5s polling) for UI consistency.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  startAutoResearch,
  listAutoResearch,
  getAutoResearch,
  deleteAutoResearch,
  resumeAutoResearch,
  streamAutoResearch,
  getEvents,
  type AutoResearchSession,
  type AutoResearchStreamEvent,
  type AutoResearchSixStepFields,
  type PersistedEvent,
} from '../lib/autoresearch-api';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { AutoResearchDetail } from './AutoResearchDetail';

// ─── Constants ────────────────────────────────────────────────

const SIX_STEPS = [
  { key: 'clarification', label: '概念澄清', num: 1, color: 'blue' },
  { key: 'evidence',      label: '建立依据', num: 2, color: 'green' },
  { key: 'reasoning',     label: '推理严密', num: 3, color: 'purple' },
  { key: 'structure',     label: '稳固结构', num: 4, color: 'orange' },
  { key: 'report',        label: '结论输出', num: 5, color: 'gray' },
  { key: 'compliance',    label: '检查清单', num: 6, color: 'cyan' },
] as const;

const STATUS_LABELS: Record<string, { icon: string; color: string; text: string }> = {
  clarifying:    { icon: '◌', color: 'text-blue-400',     text: '概念澄清中' },
  planning:      { icon: '◐', color: 'text-blue-400',     text: '规划中' },
  gathering:     { icon: '↓', color: 'text-blue-400',     text: '采集中' },
  analyzing:     { icon: '◍', color: 'text-blue-400',     text: '分析中' },
  synthesizing:  { icon: '◑', color: 'text-purple-400',   text: '综合中' },
  report:        { icon: '▤', color: 'text-orange-400',   text: '生成报告' },
  reviewing:     { icon: '✓', color: 'text-yellow-400',   text: '评审中' },
  done:          { icon: '✓', color: 'text-green-400',    text: '已完成' },
  incomplete:    { icon: '⚠', color: 'text-yellow-400',   text: '部分完成' },
  error:         { icon: '✗', color: 'text-red-400',      text: '失败' },
  timeout:       { icon: '⏱', color: 'text-red-400',      text: '超时' },
  paused:        { icon: '⏸', color: 'text-yellow-400',   text: '已暂停' },
  pausing:       { icon: '⏸', color: 'text-yellow-400',   text: '暂停中' },
  cancelling:    { icon: '⊗', color: 'text-red-400',      text: '取消中' },
  cancelled:     { icon: '⊗', color: 'text-slate-400',    text: '已取消' },
};

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

// ─── Mini 6-step progress bar ─────────────────────────────────

function MiniSixStepBar({ currentStep, status }: { currentStep: string; status: string }) {
  // Map status to step index
  let activeIdx = SIX_STEPS.findIndex(s => s.key === currentStep);
  if (activeIdx < 0) {
    if (status === 'done') activeIdx = SIX_STEPS.length;
    else if (status === 'error' || status === 'timeout') activeIdx = -1;
  }

  return (
    <div className="flex items-center gap-0.5">
      {SIX_STEPS.map((step, idx) => {
        const isCompleted = activeIdx > idx || status === 'done';
        const isCurrent = activeIdx === idx && status !== 'done';
        return (
          <div key={step.key} className="flex items-center" title={step.label}>
            <div className="relative">
              {isCurrent && (
                <div className="absolute inset-0 rounded-full bg-[var(--accent)]/30 animate-stage-pulse" />
              )}
              <div
                className={`relative w-4 h-4 rounded-full flex items-center justify-center text-[8px] font-bold transition-all ${
                  isCompleted
                    ? 'bg-[var(--accent)]/40 text-[var(--accent)]'
                    : isCurrent
                    ? 'bg-[var(--accent)] text-white ring-2 ring-[var(--accent)]/30'
                    : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] opacity-30 border border-[var(--border)]'
                }`}
              >
                {isCompleted ? '✓' : step.num}
              </div>
            </div>
            {idx < SIX_STEPS.length - 1 && (
              <div
                className={`w-1.5 h-px ${
                  isCompleted ? 'bg-[var(--accent)]/40' : 'bg-[var(--border)]'
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── SessionSidebar (left) ───────────────────────────────────

function AutoResearchSidebar({
  selectedId,
  onSelect,
  refreshKey,
}: {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  refreshKey: number;
}) {
  const { currentWikiId } = useAgentWikiStore();
  const [sessions, setSessions] = useState<AutoResearchSession[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchSessions = async () => {
      try {
        const data = await listAutoResearch(currentWikiId || undefined);
        if (mounted) {
          setSessions(data.autoresearch_sessions);
          setLoading(false);
        }
      } catch {
        if (mounted) {
          setSessions([]);
          setLoading(false);
        }
      }
    };
    fetchSessions();
    const i = setInterval(fetchSessions, 5000);
    return () => {
      mounted = false;
      clearInterval(i);
    };
  }, [currentWikiId, refreshKey]);

  const handleNew = () => {
    onSelect(null);
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteAutoResearch(id);
      if (selectedId === id) onSelect(null);
    } catch { /* silent */ }
  };

  return (
    <div className="flex flex-col h-full min-h-0 border-r border-[var(--border)]">
      <div className="p-3 border-b border-[var(--border)]">
        <button
          onClick={handleNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium
            bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
        >
          <span>＋</span>
          <span>新建研究 (6 步)</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && sessions.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">加载中...</div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="p-3 text-xs text-[var(--text-secondary)] text-center">
            暂无研究
            <div className="mt-1 text-[10px] opacity-70">点上方"新建"开始 6 步研究</div>
          </div>
        )}
        {sessions.map((s) => {
          const status = STATUS_LABELS[s.status] || STATUS_LABELS.error;
          const isSelected = selectedId === s.id;
          return (
            <div
              key={s.id}
              onClick={() => onSelect(s.id)}
              className={`relative px-3 py-2.5 border-b border-[var(--border)] cursor-pointer transition-colors
                ${isSelected ? 'bg-[var(--accent)]/10' : 'hover:bg-[var(--bg-tertiary)]'}`}
            >
              {isSelected && (
                <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-[var(--accent)]" />
              )}
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 text-[10px]">
                  <span className={status.color}>{status.icon}</span>
                  <span className={status.color}>{status.text}</span>
                </div>
                <button
                  onClick={(e) => handleDelete(e, s.id)}
                  className="text-slate-500 hover:text-red-400 text-xs"
                  title="删除"
                >
                  ✕
                </button>
              </div>
              <div className="text-xs text-[var(--text-primary)] line-clamp-2 mb-1">
                {truncate(s.query, 60)}
              </div>
              <div className="flex items-center justify-between text-[10px] text-[var(--text-secondary)]">
                <span className="font-mono">{s.id.slice(0, 8)}</span>
                <span>{formatRelativeTime(s.updated_at)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── New session form ────────────────────────────────────────

function NewSessionForm({ onCreated }: { onCreated: (id: string) => void }) {
  const { currentWikiId } = useAgentWikiStore();
  const [query, setQuery] = useState('');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    if (!query.trim()) return;
    setStarting(true);
    setError(null);
    try {
      const { sessionId } = await startAutoResearch(query.trim(), currentWikiId || undefined);
      setQuery('');
      onCreated(sessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--bg-primary)] min-h-0">
      <div className="min-h-full flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-2xl py-4">
        <div className="text-center mb-6">
          <h2 className="text-2xl font-bold text-[var(--accent)] mb-2">
            AutoResearch — 6 步逻辑框架
          </h2>
          <p className="text-sm text-[var(--text-secondary)]">
            概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单
          </p>
        </div>
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-2">
              研究问题
            </label>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="例如：2024 年 LLM 推理优化最新进展是什么？"
              className="w-full h-32 px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded
                text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)]
                focus:outline-none focus:border-[var(--accent)] resize-none"
              disabled={starting}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  handleStart();
                }
              }}
            />
            <div className="text-[10px] text-[var(--text-secondary)] mt-1">
              Cmd/Ctrl + Enter 快速开始
            </div>
          </div>
          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded p-2">
              {error}
            </div>
          )}
          <button
            onClick={handleStart}
            disabled={!query.trim() || starting}
            className="w-full px-4 py-3 rounded text-sm font-medium
              bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]
              disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {starting ? '启动中...' : '开始 6 步研究'}
          </button>
        </div>
        <div className="mt-6 grid grid-cols-2 gap-3 text-[11px]">
          {SIX_STEPS.map((s) => (
            <div
              key={s.key}
              className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded p-2"
            >
              <div className="font-bold text-[var(--accent)]">
                ⑥ {s.num}. {s.label}
              </div>
            </div>
          ))}
        </div>
        </div>
      </div>
    </div>
  );
}

// ─── Active session header ───────────────────────────────────

function SessionHeader({
  session,
  onRefresh,
  onResume,
}: {
  session: AutoResearchSession;
  onRefresh: () => void;
  onResume: () => void;
}) {
  const status = STATUS_LABELS[session.status] || STATUS_LABELS.error;
  const canResume =
    session.status === 'incomplete' ||
    session.status === 'error' ||
    session.status === 'timeout' ||
    session.status === 'done';
  return (
    <div className="p-4 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-sm font-bold ${status.color}`}>
              {status.icon} {status.text}
            </span>
            <span className="text-[10px] text-[var(--text-secondary)] font-mono">
              {session.id.slice(0, 12)}
            </span>
          </div>
          <div className="text-sm text-[var(--text-primary)] font-medium line-clamp-2">
            {session.query}
          </div>
        </div>
        <div className="flex gap-1">
          {canResume && (
            <button
              onClick={onResume}
              className="text-xs text-green-400 hover:text-green-300 px-2 py-1 rounded
                border border-green-500/30 hover:border-green-500/50 transition-colors"
              title="恢复研究（使用已有资源重新跑一轮）"
            >
              ▶ 恢复
            </button>
          )}
          <button
            onClick={onRefresh}
            className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] px-2 py-1 rounded
              border border-[var(--border)]"
            title="刷新"
          >
            ↻
          </button>
        </div>
      </div>
      <div className="mt-2">
        <MiniSixStepBar currentStep={session.current_step} status={session.status} />
      </div>
    </div>
  );
}

// ─── Tabs ────────────────────────────────────────────────────

type TabKey = 'overview' | 'sources' | 'sixstep' | 'report';

const TABS: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'overview', label: '概览',   icon: '◐' },
  { key: 'sources',  label: '来源',   icon: '↓' },
  { key: 'sixstep',  label: '6 步',   icon: '⑥' },
  { key: 'report',   label: '报告',   icon: '▤' },
];

// ─── Event log (Overview tab) ────────────────────────────────

interface EventLogEntry {
  type: string;
  message: string;
  timestamp: number;
}

function EventLog({ events }: { events: EventLogEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="text-xs text-[var(--text-secondary)] text-center py-8">
        等待事件流...
      </div>
    );
  }

  return (
    <div className="space-y-1 font-mono text-[11px]">
      {events.map((e, i) => (
        <div
          key={i}
          className={`px-2 py-1 rounded ${
            e.type === 'error' ? 'bg-red-500/10 text-red-400' :
            e.type === 'done' ? 'bg-green-500/10 text-green-400' :
            e.type.endsWith('_complete') ? 'bg-blue-500/10 text-blue-400' :
            'text-[var(--text-secondary)]'
          }`}
        >
          <span className="opacity-60">{e.type}</span> {e.message}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

// ─── Main panel ──────────────────────────────────────────────

export function AutoResearchPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [session, setSession] = useState<AutoResearchSession | null>(null);
  const [sixStep, setSixStep] = useState<AutoResearchSixStepFields | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [eventLog, setEventLog] = useState<EventLogEntry[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Load session details
  const loadSession = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const data = await getAutoResearch(id);
      setSession(data.session);
      setSixStep(data.sixStep);
    } catch (e) {
      setSession(null);
      setSixStep(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // When selectedId changes, load
  useEffect(() => {
    if (!selectedId) {
      setSession(null);
      setSixStep(null);
      setEventLog([]);
      return;
    }
    loadSession(selectedId);
  }, [selectedId, loadSession]);

  // For done/error/cancelled sessions, load historical events once
  // (the SSE stream is no longer active, so eventLog would otherwise
  // stay empty). For active sessions, the streaming useEffect below
  // will populate the log in real time.
  useEffect(() => {
    if (!selectedId || !session) return;
    const isTerminal =
      session.status === 'done' ||
      session.status === 'error' ||
      session.status === 'cancelled' ||
      session.status === 'timeout';
    if (!isTerminal) return;

    let cancelled = false;
    (async () => {
      try {
        const { events } = await getEvents(selectedId);
        if (cancelled) return;
        if (events && events.length > 0) {
          setEventLog(
            events.map((e: PersistedEvent) => ({
              type: e.type,
              message: `[历史] ${e.message ?? ''}`,
              timestamp: e.timestamp ? new Date(e.timestamp).getTime() : Date.now(),
            })),
          );
        }
      } catch {
        // Silent: historical events are best-effort
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, session?.status]);

  // Start streaming when a session is selected and not done
  useEffect(() => {
    if (!selectedId || !session) return;
    if (session.status === 'done' || session.status === 'error' || session.status === 'cancelled' || session.status === 'timeout' || session.status === 'incomplete') {
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsStreaming(true);

    const stream = streamAutoResearch(selectedId, { signal: controller.signal });
    const reader = stream.getReader();

    (async () => {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (!value) continue;

          const ev = value;
          const t = ev.type;
          let msg = '';

          if (t === 'step') msg = `${ev.step}: ${ev.message}`;
          else if (t === 'clarification_complete') {
            msg = `概念澄清完成 (scope_check=${ev.scope_check})`;
            setActiveTab('sixstep');
          } else if (t === 'evidence_scoring_complete') {
            msg = `✓ 建立依据 — ${ev.count} sources scored, avg=${ev.avg_score.toFixed(2)}`;
          } else if (t === 'reasoning_check_complete') {
            msg = `✓ 推理严密 — aggregate=${ev.aggregate_score.toFixed(2)}, ${ev.issues_count} issues`;
          } else if (t === 'structure_check_complete') {
            msg = `✓ 稳固结构 — aggregate=${ev.aggregate_score.toFixed(2)}, ${ev.issues_count} issues`;
          } else if (t === 'synthesis_complete') msg = `综合完成`;
          else if (t === 'review_passed') msg = `✓ 评审通过 (score=${ev.score})`;
          else if (t === 'review_issues') msg = `⚠ 评审发现 ${ev.issues.length} issues`;
          else if (t === 'sub_query_created') msg = `子查询: ${ev.query}`;
          else if (t === 'source_gathered') msg = `↓ 来源: ${ev.title}`;
          else if (t === 'progress') msg = `${(ev.progress * 100).toFixed(0)}% — ${ev.message}`;
          else if (t === 'reasoning') msg = `💭 ${ev.action}: ${ev.thought || ''}`;
          else if (t === 'done') {
            msg = `✓ 研究完成`;
            setActiveTab('report');
          } else if (t === 'error') msg = `✗ ${ev.error}`;
          else if (t === 'cancelled' || t === 'paused') msg = `${t}: ${ev.phase}`;
          else if (t === 'incomplete') {
            msg = `⚠ 部分完成 — ${ev.reason} (${ev.framework_completed}/${ev.framework_total} 步)`;
          } else if (t === 'framework_redirect') {
            msg = `↪ 框架不完整: ${ev.from} → ${ev.to} (${ev.reason})`;
          } else if (t === 'quality_redirect') {
            msg = `⚠ 质量不达标: ${ev.from} → ${ev.to} (${ev.reason})`;
          }

          if (msg) {
            setEventLog((prev) => [...prev, { type: t, message: msg, timestamp: Date.now() }]);
          }

          // Refresh session on key 6-step events
          if (t === 'clarification_complete' || t === 'evidence_scoring_complete'
              || t === 'reasoning_check_complete' || t === 'structure_check_complete'
              || t === 'synthesis_complete' || t === 'review_passed' || t === 'review_issues'
              || t === 'done' || t === 'error') {
            loadSession(selectedId);
          }
        }
      } catch (e) {
        // Stream aborted or errored
      } finally {
        setIsStreaming(false);
        // Final refresh
        if (selectedId) loadSession(selectedId);
      }
    })();

    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [selectedId, session?.status, loadSession]);

  const handleNew = (id: string) => {
    setRefreshKey((k) => k + 1);
    setSelectedId(id);
    setActiveTab('overview');
    setEventLog([]);
  };

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
    if (selectedId) loadSession(selectedId);
  };

  const handleResume = async () => {
    if (!selectedId) return;
    try {
      await resumeAutoResearch(selectedId);
      // Refresh session status to show "running"
      loadSession(selectedId);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      console.error('Resume failed:', e);
    }
  };

  if (!selectedId) {
    return (
      <div className="flex h-full min-h-0">
        <div className="w-72 shrink-0">
          <AutoResearchSidebar
            selectedId={selectedId}
            onSelect={setSelectedId}
            refreshKey={refreshKey}
          />
        </div>
        <NewSessionForm onCreated={handleNew} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="w-72 shrink-0">
        <AutoResearchSidebar
          selectedId={selectedId}
          onSelect={setSelectedId}
          refreshKey={refreshKey}
        />
      </div>

      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {loading && !session ? (
          <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-secondary)]">
            加载中...
          </div>
        ) : session ? (
          <>
            <SessionHeader session={session} onRefresh={handleRefresh} onResume={handleResume} />

            <div className="px-4 border-b border-[var(--border)] flex gap-1">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-3 py-2 text-xs font-medium transition-colors relative ${
                    activeTab === tab.key
                      ? 'text-[var(--accent)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  {tab.icon} {tab.label}
                  {activeTab === tab.key && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent)]" />
                  )}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto min-h-0 p-4">
              {activeTab === 'overview' && (
                <EventLog events={eventLog} />
              )}
              {activeTab === 'sources' && session && sixStep && (
                <SourcesTab session={session} sixStep={sixStep} />
              )}
              {activeTab === 'sixstep' && sixStep && session && (
                <SixStepTab sixStep={sixStep} session={session} />
              )}
              {activeTab === 'report' && session && (
                <ReportTab session={session} />
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

// ─── Sources tab ─────────────────────────────────────────────

function SourcesTab({
  session,
  sixStep,
}: {
  session: AutoResearchSession;
  sixStep: AutoResearchSixStepFields;
}) {
  const sources = session.sources || [];
  const scores = sixStep.evidence_scores || {};

  if (sources.length === 0) {
    return (
      <div className="text-xs text-[var(--text-secondary)] text-center py-8">
        暂无来源（等待采集）
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-[var(--text-secondary)] mb-2">
        {sources.length} sources
        {Object.keys(scores).length > 0 && (
          <span> · avg score {(
            Object.values(scores).reduce((a, b) => a + b, 0) / Object.values(scores).length
          ).toFixed(2)}</span>
        )}
      </div>
      {sources.map((s) => {
        const score = scores[s.id];
        return (
          <div
            key={s.id}
            className="p-2 bg-[var(--bg-secondary)] border border-[var(--border)] rounded"
          >
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="text-xs font-medium text-[var(--text-primary)] truncate flex-1">
                {s.title || s.url}
              </div>
              {score !== undefined && (
                <div
                  className={`text-[10px] font-mono font-bold ${
                    score >= 0.7 ? 'text-green-400' : score >= 0.5 ? 'text-yellow-400' : 'text-red-400'
                  }`}
                >
                  {score.toFixed(2)}
                </div>
              )}
            </div>
            {score !== undefined && (
              <div className="h-1 bg-[var(--bg-tertiary)] rounded overflow-hidden">
                <div
                  className={`h-full ${
                    score >= 0.7 ? 'bg-green-500' : score >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.min(100, score * 100)}%` }}
                />
              </div>
            )}
            <div className="text-[10px] text-[var(--text-secondary)] mt-1 font-mono truncate">
              {s.url}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 6-Step tab (dispatcher to detail) ───────────────────────

function SixStepTab({
  sixStep,
  session,
}: {
  sixStep: AutoResearchSixStepFields;
  session: AutoResearchSession;
}) {
  return <AutoResearchDetail sixStep={sixStep} session={session} />;
}

// ─── Report tab (markdown render via simple renderer) ───────

function ReportTab({ session }: { session: AutoResearchSession }) {
  // Try to extract markdown from result field
  let markdown = '';
  if (session.result) {
    try {
      const parsed = JSON.parse(session.result);
      markdown = parsed.markdown || '';
    } catch {
      markdown = session.result;
    }
  }
  // Fallback to review_json for newer sessions
  if (!markdown && session.review_json) {
    try {
      const review = JSON.parse(session.review_json);
      markdown = review.report_md || review.markdown || '';
    } catch { /* noop */ }
  }

  if (!markdown) {
    return (
      <div className="text-xs text-[var(--text-secondary)] text-center py-8">
        研究尚未生成报告
      </div>
    );
  }

  return (
    <div className="text-[12px] text-[var(--text-primary)] font-mono leading-relaxed bg-[var(--bg-secondary)] p-4 rounded border border-[var(--border)] overflow-x-auto">
      <pre className="whitespace-pre-wrap break-words">
        {markdown}
      </pre>
    </div>
  );
}
