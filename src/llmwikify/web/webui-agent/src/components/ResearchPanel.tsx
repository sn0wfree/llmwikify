import { useState, useEffect, useRef, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, type ResearchSession, type ResearchStreamEvent, type ResearchReport, type ResearchSubQuery, type ResearchSource } from '../api';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { ResearchDetail } from './ResearchDetail';

interface ActiveResearch {
  sessionId: string;
  query: string;
  status: string;
  step: string;
  progress: number;
  subQueries: ResearchSubQuery[];
  sources: Array<{ id: string; source_type: string; title: string; url: string; status: 'pending' | 'fetching' | 'done' | 'failed' }>;
  report: ResearchReport | null;
  events: string[];
  latestEvent?: string;
}

const STAGES = ['planning', 'gathering', 'analyzing', 'synthesizing', 'report', 'reviewing', 'done'];

const STAGE_LABELS: Record<string, string> = {
  planning: 'Planning',
  gathering: 'Gathering',
  analyzing: 'Analyzing',
  synthesizing: 'Synthesizing',
  report: 'Report',
  reviewing: 'Review',
  done: 'Done',
};

function formatElapsed(created: string): string {
  const ms = Date.now() - new Date(created).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function formatRelativeTime(updated: string): string {
  const ms = Date.now() - new Date(updated).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 10) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

/* ---- MiniStageBar: 7-segment compact pipeline bar ---- */

function MiniStageBar({ currentStep, status }: { currentStep: string; status: string }) {
  const currentIdx = STAGES.indexOf(status === 'done' ? 'done' : currentStep);

  return (
    <div className="flex items-center gap-0.5">
      {STAGES.map((stage, idx) => {
        const stageIdx = STAGES.indexOf(stage);
        const isCompleted = stageIdx < currentIdx;
        const isCurrent = stageIdx === currentIdx;
        const isPending = stageIdx > currentIdx;

        return (
          <div key={stage} className="flex items-center">
            <div
              className={`w-4 h-4 rounded-full flex items-center justify-center text-[8px] transition-all ${
                isCompleted ? 'bg-[var(--accent)]/40 text-[var(--accent)]' :
                isCurrent ? 'bg-[var(--accent)] text-white ring-2 ring-[var(--accent)]/30' :
                'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] opacity-30 border border-[var(--border)]'
              }`}
              title={STAGE_LABELS[stage]}
            >
              {isCompleted ? '✓' : isCurrent ? '●' : '○'}
            </div>
            {idx < STAGES.length - 1 && (
              <div className={`w-2 h-px ${
                isCompleted ? 'bg-[var(--accent)]/40' : 'bg-[var(--border)]'
              }`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---- StageStatusLine: semantic progress text per stage ---- */

function StageStatusLine({ step, status, subQueries, progress }: {
  step: string;
  status: string;
  subQueries: ResearchSubQuery[];
  progress: number;
}) {
  const doneSq = subQueries.filter(sq => sq.status === 'done').length;
  const totalSq = subQueries.length;
  const totalSources = Math.round(progress * 50);

  switch (step) {
    case 'planning':
      return totalSq > 0
        ? <span>Decomposing into {totalSq} sub-queries</span>
        : <span>Planning sub-queries...</span>;
    case 'gathering':
      if (totalSq > 0) {
        return <span>{doneSq}/{totalSq} queries done{totalSources > 0 ? ` · ${totalSources}+ sources` : ''}</span>;
      }
      return <span>Gathering sources...</span>;
    case 'analyzing':
      return totalSources > 0
        ? <span>{totalSources} sources analyzed</span>
        : <span>Analyzing sources...</span>;
    case 'synthesizing':
      return <span>Synthesizing findings...</span>;
    case 'report':
      return <span>Generating report...</span>;
    case 'reviewing':
      return <span>Reviewing report...</span>;
    case 'done':
      return <span>Research complete</span>;
    default:
      return <span>{step}...</span>;
  }
}

/* ---- SourceCard: favicon + domain chip ---- */

function SourceCard({ source }: { source: { title: string; url: string; source_type: string; status: string } }) {
  let domain = source.url;
  try { domain = new URL(source.url).hostname.replace('www.', ''); } catch { /* noop */ }
  const initial = domain[0]?.toUpperCase() || '?';

  return (
    <div className={`relative w-9 h-9 rounded border flex items-center justify-center text-[10px] font-bold shrink-0 group transition-all ${
      source.status === 'done' ? 'border-green-500/40 bg-green-500/10 text-green-400' :
      source.status === 'failed' ? 'border-red-500/40 bg-red-500/10 text-red-400' :
      source.status === 'fetching' ? 'border-yellow-500/40 bg-yellow-500/10 text-yellow-400 animate-pulse' :
      'border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)]'
    }`} title={source.title}>
      {source.source_type === 'arxiv' ? 'arXiv' : source.source_type === 'pdf' ? '📄' : initial}
      <div className="absolute -bottom-5 left-0 right-0 text-[9px] text-center truncate opacity-60 font-mono pointer-events-none group-hover:opacity-100 transition-opacity">
        {domain.slice(0, 8)}
      </div>
    </div>
  );
}

/* ---- SubQueryRow: collapsible sub-query row ---- */

function SubQueryRow({ subQuery }: { subQuery: ResearchSubQuery }) {
  const [expanded, setExpanded] = useState(false);
  const isPending = subQuery.status === 'pending' || subQuery.status === 'pending';
  const isFetching = subQuery.status === 'pending';

  return (
    <div className="text-xs">
      <div
        onClick={() => !isPending && setExpanded(e => !e)}
        className={`flex items-center gap-1.5 py-0.5 px-1 rounded ${!isPending ? 'cursor-pointer hover:bg-[var(--bg-tertiary)]' : 'opacity-60'}`}
      >
        <span className={`w-3.5 text-center text-[10px] ${
          subQuery.status === 'done' ? 'text-green-400' :
          subQuery.status === 'failed' ? 'text-red-400' :
          'text-yellow-400'
        }`}>
          {subQuery.status === 'done' ? '✓' :
           subQuery.status === 'failed' ? '✗' :
           isFetching ? '◐' : '○'}
        </span>
        <span className="text-[var(--text-secondary)] opacity-60 text-[10px]">[{subQuery.source_type}]</span>
        <span className="truncate flex-1">{subQuery.query}</span>
        {subQuery.status === 'done' && (
          <span className="text-[10px] text-green-400/60 shrink-0">done</span>
        )}
        {subQuery.status === 'failed' && (
          <span className="text-[10px] text-red-400/60 shrink-0">failed</span>
        )}
      </div>
      {expanded && subQuery.result && (
        <div className="pl-6 pr-2 py-0.5 text-[10px] text-[var(--text-secondary)] opacity-70 border-l border-[var(--border)]">
          {String(subQuery.result).slice(0, 200)}
          {String(subQuery.result).length > 200 && '...'}
        </div>
      )}
    </div>
  );
}

/* ---- CredibilityBar: 10-segment visual bar ---- */

function CredibilityBar({ score }: { score: number }) {
  const filled = Math.round(score * 10);
  const color = score >= 0.8 ? 'text-green-400' : score >= 0.5 ? 'text-yellow-400' : 'text-red-400';
  return (
    <span className={`font-mono text-[9px] ${color}`}>
      {'█'.repeat(filled)}{'░'.repeat(10 - filled)}
    </span>
  );
}

function getStageStatus(stage: string, currentStep: string, status: string): 'completed' | 'current' | 'pending' {
  if (status === 'done') return 'completed';
  if (status === 'error') {
    const sIdx = STAGES.indexOf(stage);
    const cIdx = STAGES.indexOf(currentStep);
    if (sIdx < cIdx) return 'completed';
    if (sIdx === cIdx) return 'current';
    return 'pending';
  }
  const sIdx = STAGES.indexOf(stage);
  const cIdx = STAGES.indexOf(currentStep);
  if (sIdx < cIdx) return 'completed';
  if (sIdx === cIdx) return 'current';
  return 'pending';
}

function getStageResult(stage: string, session: ResearchSession): string {
  switch (stage) {
    case 'planning': {
      const n = session.sub_query_count || 0;
      return n > 0 ? `${n} sub-queries` : '';
    }
    case 'gathering': {
      const n = session.source_count || 0;
      if (session.status === 'gathering') return `${n} sources collected`;
      if (['analyzing', 'synthesizing', 'report', 'reviewing', 'done'].includes(session.status)) return `${n} sources collected`;
      return '';
    }
    case 'analyzing': {
      const n = session.source_count || 0;
      if (session.status === 'analyzing') return `${n} sources`;
      if (['synthesizing', 'report', 'reviewing', 'done'].includes(session.status)) return `${n} analyzed`;
      return '';
    }
    case 'synthesizing': {
      if (['report', 'reviewing', 'done'].includes(session.status)) return 'Complete';
      if (session.status === 'synthesizing') return 'Synthesizing...';
      return '';
    }
    case 'report': {
      if (['reviewing', 'done'].includes(session.status)) return 'Report generated';
      if (session.status === 'report') return 'Generating...';
      return '';
    }
    case 'reviewing': {
      if (session.status === 'done') return 'Passed';
      if (session.status === 'reviewing') return 'Reviewing...';
      return '';
    }
    case 'done': {
      if (session.status === 'done') return 'Complete';
      return '';
    }
    default: return '';
  }
}

function getStageDetails(stage: string, session: ResearchSession): string[] {
  const details: string[] = [];

  switch (stage) {
    case 'planning': {
      const subQueries = session.sub_queries || [];
      subQueries.slice(0, 5).forEach(sq => {
        details.push(`${sq.query} (${sq.source_type})`);
      });
      if (subQueries.length > 5) details.push(`... ${subQueries.length - 5} more`);
      break;
    }
    case 'gathering': {
      const sources = session.sources || [];
      sources.slice(0, 5).forEach(s => {
        const title = s.title || s.url;
        details.push(`${title.slice(0, 60)} (${s.source_type})`);
      });
      if (sources.length > 5) details.push(`... ${sources.length - 5} more`);
      break;
    }
    case 'analyzing': {
      const sources = session.sources || [];
      const analyzed = sources.filter(s => s.analysis);
      analyzed.slice(0, 5).forEach(s => {
        const analysis = s.analysis as Record<string, unknown> | null;
        const score = analysis?.credibility_score || analysis?.credibility;
        const title = s.title || s.url;
        const scoreStr = score != null ? ` [${typeof score === 'number' ? Math.round(score * 100) + '%' : score}]` : '';
        details.push(`${title.slice(0, 50)}${scoreStr}`);
      });
      if (analyzed.length > 5) details.push(`... ${analyzed.length - 5} more`);
      break;
    }
    case 'synthesizing': {
      if (session.result) {
        try {
          const result = JSON.parse(session.result);
          const summary = result.synthesis_summary;
          if (summary) {
            if (summary.reinforced_claims) details.push(`${summary.reinforced_claims} reinforced claims`);
            if (summary.contradictions) details.push(`${summary.contradictions} contradictions`);
            if (summary.knowledge_gaps) details.push(`${summary.knowledge_gaps} knowledge gaps`);
          }
        } catch { /* parse error */ }
      }
      break;
    }
    case 'report': {
      if (session.result) {
        try {
          const result = JSON.parse(session.result);
          const md = result.markdown || '';
          details.push(`${md.length} characters`);
          if (result.sources) details.push(`${result.sources.length} sources cited`);
        } catch {
          details.push(`${session.result.length} characters`);
        }
      }
      break;
    }
    case 'reviewing': {
      if (session.status === 'done' && session.result) {
        details.push('Review passed');
      }
      break;
    }
  }

  return details.slice(0, 5);
}

/* ---- StagePipeline Component ---- */

export function StagePipeline({ session }: { session: ResearchSession }) {
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  const handleToggle = (stage: string) => {
    setExpandedStage(prev => prev === stage ? null : stage);
  };

  return (
    <div className="space-y-0">
      {STAGES.map((stage, idx) => {
        const stageStatus = getStageStatus(stage, session.current_step, session.status);
        const result = getStageResult(stage, session);
        const details = getStageDetails(stage, session);
        const isExpanded = expandedStage === stage;
        const canExpand = stageStatus === 'completed' && details.length > 0;
        const isLast = idx === STAGES.length - 1;

        return (
          <div key={stage}>
            {/* Stage row */}
            <div
              onClick={() => canExpand && handleToggle(stage)}
              className={`flex items-center gap-1.5 py-0.5 px-1.5 rounded transition-colors ${
                canExpand ? 'cursor-pointer hover:bg-[var(--bg-tertiary)]' : ''
              }`}
            >
              {/* Icon */}
              <span className={`w-3.5 text-center text-[10px] ${
                stageStatus === 'completed' ? 'text-green-400' :
                stageStatus === 'current' ? 'text-[var(--accent)]' :
                'text-[var(--text-secondary)] opacity-30'
              }`}>
                {stageStatus === 'completed' ? '✓' :
                 stageStatus === 'current' ? '●' : '○'}
              </span>

              {/* Label */}
              <span className={`text-xs ${
                stageStatus === 'completed' ? 'text-[var(--text-secondary)]' :
                stageStatus === 'current' ? 'text-[var(--text-primary)] font-medium' :
                'text-[var(--text-secondary)] opacity-30'
              }`}>
                {STAGE_LABELS[stage]}
              </span>

              {/* Result */}
              {result && (
                <>
                  <span className={`text-[10px] ${
                    stageStatus === 'completed' ? 'text-[var(--text-secondary)] opacity-50' :
                    stageStatus === 'current' ? 'text-[var(--text-secondary)]' :
                    'text-[var(--text-secondary)] opacity-20'
                  }`}>─</span>
                  <span className={`text-[11px] ${
                    stageStatus === 'completed' ? 'text-[var(--text-secondary)]' :
                    stageStatus === 'current' ? 'text-[var(--text-primary)]' :
                    'text-[var(--text-secondary)] opacity-30'
                  }`}>
                    {result}
                  </span>
                </>
              )}

              {/* Expand indicator */}
              {canExpand && (
                <span className="text-[10px] text-[var(--text-secondary)] opacity-40 ml-auto">
                  {isExpanded ? '▾' : '▸'}
                </span>
              )}
            </div>

            {/* Expanded details */}
            <div className={`overflow-hidden transition-all duration-200 ${
              isExpanded ? 'max-h-32 opacity-100' : 'max-h-0 opacity-0'
            }`}>
              <div className="pl-5 pb-0.5 space-y-px">
                {details.map((detail, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <div className="w-1 h-1 rounded-full bg-[var(--text-secondary)] opacity-25 shrink-0"/>
                    <span className="text-[11px] text-[var(--text-secondary)] opacity-60 truncate">{detail}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Connector line (not after last) */}
            {!isLast && (
              <div className={`ml-[6px] w-px h-1.5 ${
                stageStatus === 'completed' ? 'bg-[var(--text-secondary)] opacity-25' :
                'bg-[var(--text-secondary)] opacity-10'
              }`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ResearchPanel() {
  const { currentWikiId } = useAgentWikiStore();
  const [sessions, setSessions] = useState<ResearchSession[]>([]);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState<ActiveResearch | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const readerRef = useRef<ReadableStreamDefaultReader | null>(null);

  const loadSessions = async () => {
    try {
      const res = await api.research.list(currentWikiId || undefined);
      setSessions(res.research_sessions || []);
    } catch { /* silent */ }
  };

  useEffect(() => { loadSessions(); }, [currentWikiId]);

  const consumeStream = async (stream: ReadableStream<ResearchStreamEvent>) => {
    const reader = stream.getReader();
    readerRef.current = reader;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        handleStreamEvent(value);
      }
    } catch (e) {
      setActive(prev => prev ? { ...prev, status: 'error', events: [...prev.events, `Error: ${e}`] } : null);
    } finally {
      readerRef.current = null;
      setLoading(false);
      loadSessions();
    }
  };

  const handleStart = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setActive({
      sessionId: '',
      query: query.trim(),
      status: 'starting',
      step: '',
      progress: 0,
      subQueries: [],
      sources: [],
      report: null,
      events: [],
    });

    const stream = api.research.start(query.trim(), currentWikiId || undefined);
    setQuery('');
    await consumeStream(stream);
  };

  const handleResume = async (id: string) => {
    if (loading) return;
    setLoading(true);

    const session = sessions.find(s => s.id === id);
    setActive({
      sessionId: id,
      query: session?.query || '',
      status: 'resuming',
      step: '',
      progress: session?.progress || 0,
      subQueries: [],
      sources: [],
      report: null,
      events: ['Resuming research...'],
    });

    const stream = api.research.resume(id);
    await consumeStream(stream);
  };

  const handleStreamEvent = (event: ResearchStreamEvent) => {
    setActive(prev => {
      if (!prev) return null;
      const next = { ...prev };

      switch (event.type) {
        case 'step':
          next.step = event.step;
          next.status = event.step;
          if (event.session_id && !next.sessionId) {
            next.sessionId = event.session_id;
          }
          next.events = [...next.events, `[${event.step}] ${event.message}`];
          next.latestEvent = event.message;
          break;
        case 'sub_query_created':
          next.subQueries = [...next.subQueries, {
            id: event.sub_query_id,
            session_id: '',
            query: event.query,
            source_type: event.source_type,
            url: event.url || null,
            status: 'pending',
            result: null,
            error: null,
            created_at: '',
            completed_at: null,
          }];
          next.events = [...next.events, `Sub-query: ${event.query} (${event.source_type})`];
          next.latestEvent = `New query: ${event.query}`;
          break;
        case 'sub_query_done':
          next.subQueries = next.subQueries.map(sq =>
            sq.id === event.sub_query_id ? { ...sq, status: 'done' } : sq
          );
          next.latestEvent = 'Query complete';
          break;
        case 'sub_query_failed':
          next.subQueries = next.subQueries.map(sq =>
            sq.id === event.sub_query_id ? { ...sq, status: 'failed', error: event.error } : sq
          );
          next.events = [...next.events, `Failed: ${event.error}`];
          next.latestEvent = `Failed: ${event.error}`;
          break;
        case 'source_gathered':
          next.sources = [...next.sources, {
            id: event.source_id,
            source_type: event.source_type,
            title: event.title,
            url: event.url,
            status: 'done',
          }];
          next.events = [...next.events, `Source: ${event.title}`];
          next.latestEvent = `Source: ${event.title}`;
          break;
        case 'source_analyzed':
          next.sources = next.sources.map(s =>
            s.id === event.source_id ? { ...s, status: 'done' } : s
          );
          next.latestEvent = `Analyzed: ${event.title}`;
          break;
        case 'source_analysis_failed':
          next.sources = next.sources.map(s =>
            s.id === event.source_id ? { ...s, status: 'failed' } : s
          );
          next.events = [...next.events, `Analysis failed: ${event.error}`];
          next.latestEvent = `Analysis failed`;
          break;
        case 'progress':
          next.progress = event.progress;
          break;
        case 'synthesis_complete':
          next.events = [...next.events, `Synthesis complete`];
          next.latestEvent = `Synthesis complete`;
          break;
        case 'review_passed':
          next.events = [...next.events, `Review passed (round ${event.round}, score ${event.score})`];
          next.latestEvent = `Review passed · score ${event.score}`;
          break;
        case 'review_issues':
          next.events = [...next.events, `Review issues (round ${event.round}): ${event.issues.join(', ')}`];
          next.latestEvent = `Review issues: ${event.issues[0]}`;
          break;
        case 'review_max_rounds':
          next.events = [...next.events, event.message];
          next.latestEvent = event.message;
          break;
        case 'done':
          next.status = 'done';
          next.progress = 1;
          next.report = event.report;
          next.events = [...next.events, 'Research complete!'];
          next.latestEvent = 'Research complete!';
          break;
        case 'error':
          next.status = 'error';
          next.events = [...next.events, `Error: ${event.error}`];
          next.latestEvent = `Error: ${event.error}`;
          break;
      }
      return next;
    });
  };

  const handlePause = async (id: string) => {
    try {
      await api.research.pause(id);
      if (active?.sessionId === id) {
        setActive(prev => prev ? { ...prev, status: 'paused' } : null);
      }
      loadSessions();
    } catch { /* silent */ }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.research.delete(id);
      if (active?.sessionId === id) setActive(null);
      loadSessions();
    } catch { /* silent */ }
  };

  const handleViewReport = async (session: ResearchSession) => {
    if (session.result) {
      try {
        const parsed = JSON.parse(session.result);
        setActive({
          sessionId: session.id,
          query: session.query,
          status: 'done',
          step: 'done',
          progress: 1,
          subQueries: [],
          sources: [],
          report: parsed,
          events: [],
          latestEvent: 'Report loaded',
        });
      } catch {
        setActive({
          sessionId: session.id,
          query: session.query,
          status: 'done',
          step: 'done',
          progress: 1,
          subQueries: [],
          sources: [],
          report: { query: session.query, markdown: session.result, sources: [] },
          events: [],
          latestEvent: 'Report loaded',
        });
      }
    }
  };

  const dismissActive = () => setActive(null);

  // Detail view: show session details
  if (selectedSessionId) {
    return (
      <ResearchDetail
        sessionId={selectedSessionId}
        onBack={() => setSelectedSessionId(null)}
      />
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border)]">
        <h2 className="text-lg font-bold mb-3">Deep Research</h2>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleStart()}
            placeholder="Research topic..."
            className="flex-1 px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-sm"
            disabled={loading}
          />
          <button
            onClick={handleStart}
            disabled={loading || !query.trim()}
            className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-50"
          >
            {loading ? 'Running...' : 'Start'}
          </button>
        </div>
      </div>

      {/* Active Research */}
      {active && (
        <div className="p-4 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-sm">{active.query}</h3>
              <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                active.status === 'done' ? 'bg-green-500/20 text-green-400' :
                active.status === 'error' ? 'bg-red-500/20 text-red-400' :
                'bg-blue-500/20 text-blue-400'
              }`}>
                {active.status}
              </span>
            </div>
            <div className="flex gap-2">
              {['planning', 'gathering', 'analyzing', 'synthesizing', 'report', 'reviewing'].includes(active.status) && (
                <button onClick={() => active.sessionId && handlePause(active.sessionId)} className="text-xs text-yellow-400 hover:underline">Pause</button>
              )}
              <button onClick={dismissActive} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Dismiss</button>
            </div>
          </div>

          {/* Mini Stage Bar */}
          <div className="mb-2">
            <MiniStageBar currentStep={active.step} status={active.status === 'resuming' || active.status === 'starting' ? 'planning' : active.status} />
          </div>

          {/* Stage Status Line */}
          <div className="text-xs text-[var(--text-secondary)] mb-2 flex items-center gap-2">
            <StageStatusLine
              step={active.step || active.status}
              status={active.status}
              subQueries={active.subQueries}
              progress={active.progress}
            />
            {active.sessionId && (
              <span className="font-mono opacity-40 text-[10px]" title={active.sessionId}>
                {active.sessionId.slice(0, 8)}
              </span>
            )}
          </div>

          {/* Source Cards */}
          {active.sources.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3 pb-2" style={{ paddingBottom: '0.5rem' }}>
              {active.sources.slice(0, 8).map(src => (
                <SourceCard key={src.id} source={src} />
              ))}
              {active.sources.length > 8 && (
                <div className="w-9 h-9 rounded border border-[var(--border)] bg-[var(--bg-tertiary)] flex items-center justify-center text-[10px] text-[var(--text-secondary)]">
                  +{active.sources.length - 8}
                </div>
              )}
            </div>
          )}

          {/* Sub-queries */}
          {active.subQueries.length > 0 && (
            <div className="mb-2 max-h-36 overflow-y-auto space-y-0.5 border-l border-[var(--border)] pl-1">
              <div className="text-[10px] text-[var(--text-secondary)] opacity-50 mb-1 px-1">Sub-queries</div>
              {active.subQueries.map((sq, i) => (
                <SubQueryRow key={i} subQuery={sq} />
              ))}
            </div>
          )}

          {/* Latest Event (highlighted) */}
          {active.latestEvent && ['planning', 'gathering', 'analyzing', 'synthesizing', 'report', 'reviewing'].includes(active.status) && (
            <div className="text-xs text-[var(--accent)] font-medium mb-1 animate-pulse">
              ▶ {active.latestEvent}
            </div>
          )}

          {/* Events log (collapsed, last 5) */}
          {active.events.length > 0 && (
            <div className="max-h-20 overflow-y-auto space-y-0.5 opacity-50">
              {active.events.slice(-5).map((evt, i) => (
                <div key={i} className="text-[11px] text-[var(--text-secondary)]">{evt}</div>
              ))}
            </div>
          )}

          {/* Report view */}
          {active.report && (
            <div className="mt-3 p-3 bg-[var(--bg-primary)] rounded border border-[var(--border)]">
              <h4 className="text-sm font-medium mb-2">Report: {active.report.query}</h4>
              <div className="prose prose-sm max-h-96 overflow-y-auto text-xs
                prose-headings:mt-2 prose-headings:mb-1
                prose-p:my-1 prose-ul:my-1 prose-ol:my-1
                prose-li:my-0 prose-a:text-[var(--accent)] prose-a:underline
                prose-blockquote:border-l-2 prose-blockquote:border-[var(--border)] prose-blockquote:pl-2 prose-blockquote:italic
              ">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{active.report.markdown}</ReactMarkdown>
              </div>
              {active.report.sources && active.report.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-[var(--border)]">
                  <div className="text-xs text-[var(--text-secondary)]">Sources: {active.report.sources.length}</div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Sessions list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {sessions.length === 0 ? (
          <div className="text-sm text-[var(--text-secondary)] text-center py-8">No research sessions yet</div>
        ) : (
          sessions.map(s => {
            const isActive = ['planning', 'gathering', 'analyzing', 'synthesizing', 'report', 'reviewing'].includes(s.status);
            return (
              <div
                key={s.id}
                onClick={() => setSelectedSessionId(s.id)}
                className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--border)] cursor-pointer hover:border-[var(--accent)] transition-colors"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium truncate flex-1 mr-2">{s.query}</span>
                  <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${
                    s.status === 'done' ? 'bg-green-500/20 text-green-400' :
                    s.status === 'error' ? 'bg-red-500/20 text-red-400' :
                    s.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-blue-500/20 text-blue-400'
                  }`}>
                    {s.status}
                  </span>
                </div>

                {/* Mini Stage Bar */}
                <div className="mb-2">
                  <MiniStageBar currentStep={s.current_step} status={s.status} />
                </div>

                {/* Current Stage Status Line */}
                {isActive && (
                  <div className="text-xs text-[var(--text-secondary)] mb-2">
                    <StageStatusLine step={s.current_step} status={s.status} subQueries={s.sub_queries || []} progress={s.progress} />
                  </div>
                )}
                {s.status === 'done' && s.result && (
                  <div className="text-xs text-green-400/70 mb-2">
                    Done · {(() => {
                      try { const r = JSON.parse(s.result!); return `${r.markdown?.length || 0} chars · ${r.sources?.length || 0} sources`; } catch { return 'Report generated'; }
                    })()}
                  </div>
                )}

                {/* Time + ID */}
                <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                  {isActive && (
                    <span title={`Created: ${new Date(s.created_at).toLocaleString()}`}>
                      {formatElapsed(s.created_at)} elapsed
                    </span>
                  )}
                  {isActive && <span className="opacity-40">·</span>}
                  <span title={new Date(s.updated_at).toLocaleString()}>
                    {formatRelativeTime(s.updated_at)}
                  </span>
                  <span className="opacity-40">·</span>
                  <span className="font-mono opacity-40 text-[10px]" title={s.id}>{s.id.slice(0, 8)}</span>
                </div>

                <div className="flex gap-2 mt-2" onClick={e => e.stopPropagation()}>
                  {s.status === 'done' && (
                    <button onClick={() => setSelectedSessionId(s.id)} className="text-xs text-[var(--accent)] hover:underline">View Details</button>
                  )}
                  {(s.status === 'paused' || s.status === 'gathering') && (
                    <button onClick={() => handleResume(s.id)} className="text-xs text-green-400 hover:underline">Resume</button>
                  )}
                  {isActive && (
                    <button onClick={() => handlePause(s.id)} className="text-xs text-yellow-400 hover:underline">Pause</button>
                  )}
                  {s.status !== 'done' && (
                    <button onClick={() => handleDelete(s.id)} className="text-xs text-red-400 hover:underline">Delete</button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
