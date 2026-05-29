import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, type ResearchSession, type ResearchSource } from '../api';
import { ResearchRating } from './ResearchRating';
import { StagePipeline } from './ResearchPanel';
import { SaveToWikiModal } from './SaveToWikiModal';

interface Props {
  sessionId: string;
  onBack: () => void;
}

const STAGE_LABELS: Record<string, string> = {
  planning: 'Planning sub-queries',
  gathering: 'Gathering sources',
  analyzing: 'Analyzing sources',
  synthesizing: 'Synthesizing findings',
  report: 'Generating report',
  reviewing: 'Reviewing report',
  done: 'Completed',
  error: 'Error',
  paused: 'Paused',
};

function parseReport(result: string | null) {
  if (!result) return null;
  try {
    return JSON.parse(result);
  } catch {
    return { query: '', markdown: result, sources: [] };
  }
}

export function ResearchDetail({ sessionId, onBack }: Props) {
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showRating, setShowRating] = useState(false);
  const [saveModalOpen, setSaveModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [sess, src] = await Promise.all([
          api.research.get(sessionId),
          api.research.sources(sessionId),
        ]);
        if (!cancelled) {
          setSession(sess);
          setSources(src.sources || []);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [sessionId]);

  if (loading) {
    return (
      <div className="h-full flex flex-col">
        <Header onBack={onBack} />
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-secondary)]">
          Loading details...
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="h-full flex flex-col">
        <Header onBack={onBack} />
        <div className="flex-1 flex items-center justify-center text-sm text-red-400">
          {error || 'Session not found'}
        </div>
      </div>
    );
  }

  const report = parseReport(session.result);
  const subQueries = session.sub_queries || [];
  const isRunning = ['planning', 'gathering', 'analyzing', 'synthesizing', 'report', 'reviewing'].includes(session.status);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <Header
        onBack={onBack}
        canSave={session.status === 'done'}
        onSaveToWiki={() => setSaveModalOpen(true)}
      />

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Query title & status */}
        <Section title={session.query}>
          <div className="flex items-center gap-3 flex-wrap">
            <StatusBadge status={session.status} />
            <span className="text-xs text-[var(--text-secondary)]">
              Created {new Date(session.created_at).toLocaleString()}
            </span>
            {session.updated_at !== session.created_at && (
              <span className="text-xs text-[var(--text-secondary)]">
                Updated {new Date(session.updated_at).toLocaleString()}
              </span>
            )}
          </div>
        </Section>

        {/* Stage Pipeline */}
        <Section title="Progress">
          <StagePipeline session={session} />
        </Section>

        {/* Sub-queries */}
        {subQueries.length > 0 && (
          <Section title={`Sub-queries (${subQueries.length})`}>
            <div className="space-y-1.5">
              {subQueries.map(sq => (
                <div key={sq.id} className="flex items-center gap-2 text-xs">
                  <span className={
                    sq.status === 'done' ? 'text-green-500' :
                    sq.status === 'failed' ? 'text-red-500' :
                    'text-yellow-500'
                  }>
                    {sq.status === 'done' ? '\u2713' : sq.status === 'failed' ? '\u2717' : '\u25CB'}
                  </span>
                  <span className="text-[var(--text-secondary)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded">
                    {sq.source_type}
                  </span>
                  <span className="flex-1 truncate">{sq.query}</span>
                  {sq.error && (
                    <span className="text-red-400 truncate max-w-[200px]" title={sq.error}>
                      {sq.error}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Sources */}
        {sources.length > 0 && (
          <Section title={`Sources (${sources.length})`}>
            <div className="space-y-2">
              {sources.map(src => (
                <SourceCard key={src.id} source={src} />
              ))}
            </div>
          </Section>
        )}

        {/* Report */}
        {report && report.markdown && (
          <Section title="Report">
            <div className="prose prose-sm max-h-[32rem] overflow-y-auto text-xs
              prose-headings:mt-3 prose-headings:mb-1
              prose-p:my-1 prose-ul:my-1 prose-ol:my-1
              prose-li:my-0 prose-a:text-[var(--accent)] prose-a:underline
              prose-blockquote:border-l-2 prose-blockquote:border-[var(--border)] prose-blockquote:pl-2 prose-blockquote:italic
            ">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.markdown}</ReactMarkdown>
            </div>
            {report.sources && report.sources.length > 0 && (
              <div className="mt-2 pt-2 border-t border-[var(--border)] text-xs text-[var(--text-secondary)]">
                Cited sources: {report.sources.length}
              </div>
            )}
          </Section>
        )}

        {/* Rating */}
        {session.status === 'done' && report && (
          <Section title="Feedback">
            {showRating ? (
              <ResearchRating
                researchId={sessionId}
                report={report}
                onClose={() => setShowRating(false)}
              />
            ) : (
              <button
                onClick={() => setShowRating(true)}
                className="text-xs text-[var(--accent)] hover:underline"
              >
                Rate this research
              </button>
            )}
          </Section>
        )}
      </div>

      {saveModalOpen && (
        <SaveToWikiModal
          sessionId={sessionId}
          query={session.query}
          onClose={() => setSaveModalOpen(false)}
        />
      )}
    </div>
  );
}

/* ---- Sub-components ---- */

function Header({ onBack, onSaveToWiki, canSave }: { onBack: () => void; onSaveToWiki?: () => void; canSave?: boolean }) {
  return (
    <div className="p-4 border-b border-[var(--border)] flex items-center gap-3">
      <button onClick={onBack} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <path d="M11 2L5 8l6 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      <h2 className="text-sm font-medium flex-1">Research Details</h2>
      {canSave && onSaveToWiki && (
        <button
          onClick={onSaveToWiki}
          className="text-xs px-2 py-1 rounded text-[var(--accent)] hover:bg-[var(--accent)]/10"
        >
          Save to Wiki
        </button>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--border)]">
      <h3 className="text-xs font-medium text-[var(--text-secondary)] mb-2">{title}</h3>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === 'done' ? 'bg-green-500/20 text-green-400' :
    status === 'error' ? 'bg-red-500/20 text-red-400' :
    status === 'paused' ? 'bg-yellow-500/20 text-yellow-400' :
    'bg-blue-500/20 text-blue-400';
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${color}`}>
      {STAGE_LABELS[status] || status}
    </span>
  );
}

function SourceCard({ source }: { source: ResearchSource }) {
  const [expanded, setExpanded] = useState(false);

  const analysis = source.analysis as Record<string, unknown> | null;
  const summary = analysis?.summary || analysis?.text || '';
  const credibility = analysis?.credibility_score || analysis?.credibility;

  return (
    <div className="p-2 bg-[var(--bg-tertiary)] rounded text-xs">
      <div className="flex items-start gap-2">
        <span className="text-[var(--text-secondary)] bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded shrink-0">
          {source.source_type}
        </span>
        <div className="flex-1 min-w-0">
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:underline block truncate"
            title={source.url}
          >
            {source.title || source.url}
          </a>
          {summary && (
            <p className="text-[var(--text-secondary)] mt-1 line-clamp-2">
              {typeof summary === 'string' ? summary : JSON.stringify(summary)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {credibility != null && (
            <span className={`px-1.5 py-0.5 rounded ${
              Number(credibility) >= 0.8 ? 'bg-green-500/20 text-green-400' :
              Number(credibility) >= 0.5 ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-red-500/20 text-red-400'
            }`}>
              {typeof credibility === 'number' ? `${Math.round(credibility * 100)}%` : String(credibility)}
            </span>
          )}
          {source.rating != null && (
            <span className="text-yellow-400">
              {'\u2605'} {source.rating}
            </span>
          )}
        </div>
      </div>
      {source.content_preview && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          {expanded ? '\u25B2 Collapse' : '\u25BC Preview'}
        </button>
      )}
      {expanded && source.content_preview && (
        <div className="mt-1 p-2 bg-[var(--bg-secondary)] rounded text-[var(--text-secondary)] max-h-32 overflow-y-auto whitespace-pre-wrap">
          {source.content_preview}
        </div>
      )}
    </div>
  );
}
