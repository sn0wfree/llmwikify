import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, type ResearchSession, type ResearchStreamEvent, type ResearchReport, type ResearchSubQuery } from '../api';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { ResearchDetail } from './ResearchDetail';

interface ActiveResearch {
  sessionId: string;
  query: string;
  status: string;
  step: string;
  progress: number;
  subQueries: ResearchSubQuery[];
  report: ResearchReport | null;
  events: string[];
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

    // Find the session to show context
    const session = sessions.find(s => s.id === id);
    setActive({
      sessionId: id,
      query: session?.query || '',
      status: 'resuming',
      step: '',
      progress: session?.progress || 0,
      subQueries: [],
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
          break;
        case 'sub_query_done':
          next.subQueries = next.subQueries.map(sq =>
            sq.id === event.sub_query_id ? { ...sq, status: 'done' } : sq
          );
          break;
        case 'sub_query_failed':
          next.subQueries = next.subQueries.map(sq =>
            sq.id === event.sub_query_id ? { ...sq, status: 'failed', error: event.error } : sq
          );
          next.events = [...next.events, `Failed: ${event.error}`];
          break;
        case 'source_gathered':
          next.events = [...next.events, `Source: ${event.title}`];
          break;
        case 'source_analyzed':
          next.events = [...next.events, `Analyzed: ${event.title}`];
          break;
        case 'source_analysis_failed':
          next.events = [...next.events, `Analysis failed: ${event.error}`];
          break;
        case 'progress':
          next.progress = event.progress;
          break;
        case 'synthesis_complete':
          next.events = [...next.events, `Synthesis complete`];
          break;
        case 'review_passed':
          next.events = [...next.events, `Review passed (round ${event.round}, score ${event.score})`];
          break;
        case 'review_issues':
          next.events = [...next.events, `Review issues (round ${event.round}): ${event.issues.join(', ')}`];
          break;
        case 'review_max_rounds':
          next.events = [...next.events, event.message];
          break;
        case 'done':
          next.status = 'done';
          next.progress = 1;
          next.report = event.report;
          next.events = [...next.events, 'Research complete!'];
          break;
        case 'error':
          next.status = 'error';
          next.events = [...next.events, `Error: ${event.error}`];
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
          report: parsed,
          events: [],
        });
      } catch {
        setActive({
          sessionId: session.id,
          query: session.query,
          status: 'done',
          step: 'done',
          progress: 1,
          subQueries: [],
          report: { query: session.query, markdown: session.result, sources: [] },
          events: [],
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
            <h3 className="font-medium text-sm">{active.query}</h3>
            <div className="flex gap-2">
              {(active.status === 'planning' || active.status === 'gathering' || active.status === 'analyzing' || active.status === 'synthesizing' || active.status === 'report' || active.status === 'reviewing') && (
                <button onClick={() => active.sessionId && handlePause(active.sessionId)} className="text-xs text-yellow-400 hover:underline">Pause</button>
              )}
              <button onClick={dismissActive} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Dismiss</button>
            </div>
          </div>

          {/* Progress bar */}
          <div className="h-1.5 bg-[var(--bg-tertiary)] rounded-full mb-2">
            <div
              className="h-full bg-[var(--accent)] rounded-full transition-all duration-300"
              style={{ width: `${Math.round(active.progress * 100)}%` }}
            />
          </div>

          <div className="text-xs text-[var(--text-secondary)] mb-2">
            Status: {active.status} {active.step !== active.status && `(${active.step})`} — {Math.round(active.progress * 100)}%
          </div>

          {/* Sub-queries */}
          {active.subQueries.length > 0 && (
            <div className="space-y-1 mb-2 max-h-32 overflow-y-auto">
              {active.subQueries.map((sq, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={sq.status === 'done' ? 'text-green-500' : sq.status === 'failed' ? 'text-red-500' : 'text-yellow-500'}>
                    {sq.status === 'done' ? '\u2713' : sq.status === 'failed' ? '\u2717' : '\u27F3'}
                  </span>
                  <span className="text-[var(--text-secondary)]">[{sq.source_type}]</span>
                  <span>{sq.query}</span>
                </div>
              ))}
            </div>
          )}

          {/* Events log */}
          <div className="max-h-40 overflow-y-auto space-y-0.5">
            {active.events.slice(-20).map((evt, i) => (
              <div key={i} className="text-xs text-[var(--text-secondary)]">{evt}</div>
            ))}
          </div>

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
          sessions.map(s => (
            <div
              key={s.id}
              onClick={() => setSelectedSessionId(s.id)}
              className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--border)] cursor-pointer hover:border-[var(--accent)] transition-colors"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium">{s.query}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  s.status === 'done' ? 'bg-green-500/20 text-green-400' :
                  s.status === 'error' ? 'bg-red-500/20 text-red-400' :
                  s.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400' :
                  'bg-blue-500/20 text-blue-400'
                }`}>
                  {s.status}
                </span>
              </div>
              <div className="text-xs text-[var(--text-secondary)] mb-2">
                {s.sub_query_count || 0} sub-queries · {s.source_count || 0} sources · {new Date(s.created_at).toLocaleString()}
              </div>
              <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                {s.status === 'done' && (
                  <button onClick={() => setSelectedSessionId(s.id)} className="text-xs text-[var(--accent)] hover:underline">View Details</button>
                )}
                {s.status === 'paused' && (
                  <button onClick={() => handleResume(s.id)} className="text-xs text-green-400 hover:underline">Resume</button>
                )}
                {(s.status === 'planning' || s.status === 'gathering' || s.status === 'analyzing' || s.status === 'synthesizing') && (
                  <button onClick={() => handlePause(s.id)} className="text-xs text-yellow-400 hover:underline">Pause</button>
                )}
                {s.status !== 'done' && (
                  <button onClick={() => handleDelete(s.id)} className="text-xs text-red-400 hover:underline">Delete</button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
