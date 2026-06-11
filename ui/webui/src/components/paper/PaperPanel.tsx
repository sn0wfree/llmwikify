/**
 * PaperPanel — paper reproduction main panel (v0.4.0).
 *
 * Three sub-regions (matches ReproductionPanel layout):
 *   1. Left: PaperSessionSidebar (history list + new session button)
 *   2. Right top: session header (status, paper_id, source_ref, refresh)
 *   3. Right body: one of
 *      - Form  (selectedId === null)
 *      - Progress  (status in pending/extracting/wiki_building)
 *      - Results  (status === done) — extraction + artifacts
 *      - Error   (status === error)
 *
 * Backend pipeline: POST /start → async task emits 5 events
 * (extract.started, extract.llm_done, wiki.building, wiki.written,
 * finalize.done). Frontend polls every 2s and maps events to 4-step
 * progress bar.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  FileText,
  Beaker,
  TrendingUp,
  ExternalLink,
  RefreshCw,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PaperForm } from './PaperForm';
import { PaperSessionSidebar } from './PaperSessionSidebar';
import {
  PAPER_FIVE_PHASES,
  PAPER_STATUS_LABELS,
  getPaperStatus,
  paperEventToPhase,
  startPaper,
  type PaperArtifact,
  type PaperEvent,
  type PaperSession,
  POLL_INTERVAL_MS,
} from '../../lib/paper-api';
import { Button } from '../ui/Button';

interface Artifact {
  kind: string;
  wiki_page: string;
  page_type: string;
}

interface ExtractionPayload {
  strategy_logic?: Record<string, string>;
  data_requirements?: Record<string, unknown>;
  risks?: Record<string, string[]>;
  suggested_signal?: Record<string, unknown>;
}

interface PaperDetail {
  session: PaperSession;
  events: PaperEvent[];
  artifacts: Artifact[];
  extraction: ExtractionPayload | null;
  pages_written: number;
}

// ─── Component ──────────────────────────────────────────────

export function PaperPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PaperDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── Polling lifecycle ──────────────────────────────────────
  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const loadDetail = useCallback(async (sid: string) => {
    try {
      const data = await getPaperStatus(sid);
      const extractionEvent = data.events.find((e) => e.event_type === 'extract.llm_done');
      let extraction: ExtractionPayload | null = null;
      if (extractionEvent?.payload_json) {
        try {
          const payload = JSON.parse(extractionEvent.payload_json);
          if (payload && typeof payload === 'object' && 'extraction' in payload) {
            extraction = payload.extraction as ExtractionPayload;
          }
        } catch { /* ignore */ }
      }
      // Fallback: read wiki page if extraction not in event
      if (!extraction) {
        try {
          // Try reading the most recent wiki page for this session
          extraction = null;
        } catch { /* ignore */ }
      }
      setDetail({
        session: data.session,
        events: data.events,
        artifacts: data.artifacts.map((a: PaperArtifact) => ({
          kind: a.kind,
          wiki_page: a.wiki_page,
          page_type: a.kind,
        })),
        extraction,
        pages_written: data.artifacts.length,
      });
    } catch (e) {
      console.error('failed to load paper status:', e);
    }
  }, []);

  const startPolling = useCallback((sid: string) => {
    stopPolling();
    loadDetail(sid);
    pollTimer.current = setInterval(() => {
      loadDetail(sid).then(() => {
        // Stop polling when terminal status reached
        // (loadDetail updates detail, effect below checks)
      });
    }, POLL_INTERVAL_MS);
  }, [loadDetail, stopPolling]);

  // Stop polling on terminal status
  useEffect(() => {
    if (!detail) return;
    if (detail.session.status === 'done' || detail.session.status === 'error') {
      stopPolling();
    }
  }, [detail, stopPolling]);

  // Cleanup on unmount
  useEffect(() => stopPolling, [stopPolling]);

  // ─── Handlers ───────────────────────────────────────────────
  const handleSelect = useCallback((id: string | null) => {
    setSelectedId(id);
    setSubmitError(null);
    if (id === null) {
      setDetail(null);
      stopPolling();
    } else {
      setLoading(true);
      startPolling(id);
      setLoading(false);
    }
  }, [startPolling, stopPolling]);

  const handleSubmit = async (req: {
    paper_id: string;
    source_type: 'pdf' | 'url' | 'raw';
    source_ref: string;
    paper_content: string;
  }) => {
    setSubmitError(null);
    try {
      const res = await startPaper({
        paper_id: req.paper_id,
        source_type: req.source_type,
        source_ref: req.source_ref,
        paper_content: req.paper_content,
      });
      setSelectedId(res.session_id);
      setDetail(null);
      startPolling(res.session_id);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
      throw e; // PaperForm catches and shows
    }
  };

  const handleReset = () => {
    setSelectedId(null);
    setDetail(null);
    stopPolling();
  };

  const handleRefresh = () => {
    if (selectedId) loadDetail(selectedId);
  };

  // ─── Render: sidebar + main ────────────────────────────────
  return (
    <div className="flex h-full min-h-0">
      <div className="w-64 shrink-0">
        <PaperSessionSidebar selectedId={selectedId} onSelect={handleSelect} />
      </div>
      <div className="flex-1 min-w-0 flex flex-col">
        {selectedId === null ? (
          <EmptyState onSubmit={handleSubmit} loading={loading} error={submitError} />
        ) : detail === null ? (
          <LoadingState />
        ) : detail.session.status === 'done' ? (
          <ResultsState detail={detail} onReset={handleReset} onRefresh={handleRefresh} />
        ) : detail.session.status === 'error' ? (
          <ErrorState detail={detail} onReset={handleReset} onRefresh={handleRefresh} />
        ) : (
          <ProgressState detail={detail} onReset={handleReset} />
        )}
      </div>
    </div>
  );
}

// ─── Sub-states ─────────────────────────────────────────────

function EmptyState({
  onSubmit,
  loading,
  error,
}: {
  onSubmit: (req: {
    paper_id: string;
    source_type: 'pdf' | 'url' | 'raw';
    source_ref: string;
    paper_content: string;
  }) => Promise<void>;
  loading: boolean;
  error: string | null;
}) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="p-4 border-b border-border bg-card">
        <div className="flex items-center gap-2 mb-1">
          <FileText className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">论文理解</h2>
        </div>
        <p className="text-xs text-muted-foreground">
          从论文/研报中结构化抽取策略逻辑、因子定义、风险分析
        </p>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <PaperForm onSubmit={onSubmit} />
        {loading && (
          <div className="mt-4 text-center text-sm text-muted-foreground animate-pulse">
            正在提交...
          </div>
        )}
        {error && (
          <div className="mt-3 text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg p-2">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-xs text-muted-foreground animate-pulse">加载中...</div>
    </div>
  );
}

function ProgressState({
  detail,
  onReset,
}: {
  detail: PaperDetail;
  onReset: () => void;
}) {
  const status = PAPER_STATUS_LABELS[detail.session.status];
  const currentPhase = (() => {
    for (let i = detail.events.length - 1; i >= 0; i--) {
      const phase = paperEventToPhase(detail.events[i].event_type);
      if (phase) return phase;
    }
    return null;
  })();

  return (
    <div className="flex flex-col h-full min-h-0">
      <SessionHeader detail={detail} onReset={onReset} onRefresh={() => {}} />
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            提取进度
          </h3>
          <div className="bg-card border border-border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className={cn('text-sm font-medium', status.color)}>
                {status.icon} {status.text}
              </span>
              <span className="text-[10px] text-muted-foreground font-mono">
                {detail.session.id.slice(0, 12)}
              </span>
            </div>
            <PhaseBar currentPhase={currentPhase} status={detail.session.status} />
            <div className="mt-3 grid grid-cols-4 gap-2">
              {PAPER_FIVE_PHASES.map((p) => {
                const isCurrent = p.key === currentPhase;
                return (
                  <div
                    key={p.key}
                    className={cn(
                      'text-xs px-2 py-1.5 rounded border',
                      isCurrent
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground',
                    )}
                  >
                    <div className="font-medium">{p.num}. {p.label}</div>
                    <div className="text-[10px] opacity-70">{p.desc}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <EventLogPanel events={detail.events} />
      </div>
    </div>
  );
}

function ResultsState({
  detail,
  onReset,
  onRefresh,
}: {
  detail: PaperDetail;
  onReset: () => void;
  onRefresh: () => void;
}) {
  const extraction = detail.extraction || ({} as ExtractionPayload);
  const logic = extraction.strategy_logic;
  const data = extraction.data_requirements;
  const risks = extraction.risks;
  const suggested = extraction.suggested_signal;

  return (
    <div className="flex flex-col h-full min-h-0">
      <SessionHeader detail={detail} onReset={onReset} onRefresh={onRefresh} />
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {logic && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              策略逻辑
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(logic).map(([key, value]) => (
                <div key={key} className="bg-card border border-border rounded-lg p-3">
                  <div className="text-[10px] text-muted-foreground mb-1">{key}</div>
                  <div className="text-xs text-foreground">{value}</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {data && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              数据需求
            </h3>
            <div className="bg-card border border-border rounded-lg p-3">
              {Object.entries(data).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-muted-foreground">{key}:</span>
                  <span className="text-foreground">
                    {Array.isArray(value) ? value.join(', ') : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {risks && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              风险与偏差
            </h3>
            <div className="bg-card border border-border rounded-lg p-3 space-y-1">
              {Object.entries(risks).map(([key, items]) => (
                <div key={key}>
                  <div className="text-[10px] text-muted-foreground mb-1">{key}</div>
                  {items.map((item, i) => (
                    <div key={i} className="text-xs text-foreground pl-2">- {item}</div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        )}

        {suggested && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              建议信号
            </h3>
            <div className="bg-card border border-border rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-primary/10 text-primary">
                  {String(suggested.signal_type)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  confidence: {String(suggested.confidence)}
                </span>
              </div>
              <div className="text-xs text-foreground">{String(suggested.reasoning)}</div>
            </div>
          </section>
        )}

        {!extraction && (
          <div className="text-xs text-muted-foreground bg-muted/50 border border-border rounded-lg p-3">
            提取已完成，但无 LLM 提取结果（events 数: {detail.events.length}）
          </div>
        )}

        {detail.artifacts.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              产出 ({detail.artifacts.length})
            </h3>
            <div className="space-y-2">
              {detail.artifacts.map((a) => {
                const Icon = a.kind === 'Factor' ? Beaker
                  : a.kind === 'Strategy' ? TrendingUp
                  : FileText;
                return (
                  <div
                    key={a.wiki_page}
                    className="bg-card border border-border rounded-lg p-3
                      hover:border-primary/40 transition-colors group"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center">
                          <Icon className="w-3.5 h-3.5 text-primary" />
                        </div>
                        <div>
                          <div className="text-sm font-medium text-foreground">{a.kind}</div>
                          <div className="text-[10px] text-muted-foreground font-mono">
                            {a.wiki_page}
                          </div>
                        </div>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-muted-foreground
                        group-hover:text-primary transition-colors" />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <EventLogPanel events={detail.events} />
      </div>
    </div>
  );
}

function ErrorState({
  detail,
  onReset,
  onRefresh,
}: {
  detail: PaperDetail;
  onReset: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <SessionHeader detail={detail} onReset={onReset} onRefresh={onRefresh} />
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <section>
          <h3 className="text-xs font-semibold text-destructive uppercase tracking-wider mb-2">
            提取失败
          </h3>
          <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-3">
            <div className="text-xs text-destructive">
              {detail.session.error || '未知错误'}
            </div>
          </div>
        </section>
        <EventLogPanel events={detail.events} />
      </div>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────

function SessionHeader({
  detail,
  onReset,
  onRefresh,
}: {
  detail: PaperDetail;
  onReset: () => void;
  onRefresh: () => void;
}) {
  const status = PAPER_STATUS_LABELS[detail.session.status] || PAPER_STATUS_LABELS.error;
  return (
    <div className="p-4 border-b border-border bg-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <FileText className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold">论文理解</h2>
            <span className={cn('text-[10px] px-1.5 py-0.5 rounded', status.color,
              'bg-muted')}>
              {status.icon} {status.text}
            </span>
          </div>
          <div className="text-xs text-muted-foreground font-mono truncate">
            {detail.session.paper_id} · {detail.session.source_type} ·
            <span title={detail.session.source_ref}>
              {detail.session.source_ref.length > 40
                ? detail.session.source_ref.slice(0, 40) + '...'
                : detail.session.source_ref}
            </span>
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {detail.pages_written} pages · {detail.events.length} events
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={onRefresh}
            className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded
              border border-border"
            title="刷新"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
          <Button
            onClick={onReset}
            variant="secondary"
            size="sm"
            className="text-xs"
          >
            <X className="w-3 h-3 mr-1" />
            新建
          </Button>
        </div>
      </div>
    </div>
  );
}

function PhaseBar({
  currentPhase,
  status,
}: {
  currentPhase: string | null;
  status: string;
}) {
  const activeIdx = PAPER_FIVE_PHASES.findIndex((p) => p.key === currentPhase);
  const effectiveIdx = activeIdx >= 0
    ? activeIdx
    : status === 'done' ? PAPER_FIVE_PHASES.length : -1;
  return (
    <div className="flex items-center gap-1">
      {PAPER_FIVE_PHASES.map((step, idx) => {
        const isCompleted = effectiveIdx > idx || status === 'done';
        const isCurrent = effectiveIdx === idx && status !== 'done';
        const isFailed = status === 'error' && effectiveIdx === idx;
        return (
          <div key={step.key} className="flex items-center" title={`${step.num}. ${step.label}`}>
            <div className="relative">
              {isCurrent && (
                <div className="absolute inset-0 rounded-full bg-primary/30 animate-stage-pulse" />
              )}
              <div
                className={cn(
                  'relative rounded-full flex items-center justify-center font-bold transition-all text-[10px]',
                  isCompleted && 'bg-primary/40 text-primary',
                  isCurrent && 'bg-primary text-white ring-2 ring-primary/30',
                  isFailed && 'bg-destructive/40 text-destructive',
                  !isCompleted && !isCurrent && !isFailed &&
                    'bg-muted text-muted-foreground opacity-30 border border-border'
                )}
                style={{ width: 28, height: 28 }}
              >
                {isCompleted ? '✓' : isFailed ? '✗' : step.num}
              </div>
            </div>
            {idx < PAPER_FIVE_PHASES.length - 1 && (
              <div
                className={cn(
                  'w-3 h-px',
                  isCompleted ? 'bg-primary/40' : 'bg-border'
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function EventLogPanel({ events }: { events: PaperEvent[] }) {
  return (
    <section>
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
        事件日志 ({events.length})
      </h3>
      <div className="bg-card border border-border rounded-lg p-2 max-h-40 overflow-y-auto space-y-1">
        {events.length === 0 ? (
          <div className="text-xs text-muted-foreground px-2 py-1">暂无事件</div>
        ) : (
          events.map((e) => {
            let payload: Record<string, unknown> = {};
            try { payload = JSON.parse(e.payload_json); } catch { /* keep */ }
            return (
              <div key={e.id} className="flex items-start gap-2 text-[10px] font-mono">
                <span className="text-muted-foreground shrink-0">
                  {e.created_at?.slice(11, 19) || '??:??:??'}
                </span>
                <span className="text-primary shrink-0">{e.event_type}</span>
                <span className="text-muted-foreground truncate flex-1">
                  {Object.keys(payload).length > 0 ? JSON.stringify(payload) : ''}
                </span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
